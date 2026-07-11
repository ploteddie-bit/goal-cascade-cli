"""Cascade Executor — le moteur d'execution de la cascade G.O.A.L.

Phase 1 (POC) :
- Executeur lineaire (iteration 1 -> 4)
- State JSON persistant
- Limite absolue de 5 iterations
- Verdict STOP/CONTINUE

Phase ulterieures :
- Synthesizer (synthese orientee objectif)
- Detection de derive (cosinus)
- Budget tracker
"""

from __future__ import annotations

import re
import uuid

from ..audit_journal import AuditJournal, redact_sensitive
from ..prompts import PromptLoader
from ..providers.base import BaseProvider
from ..schemas.models import (
    CascadeState,
    IterationRole,
    LLMCallRecord,
    Verdict,
    Variant,
)
from . import state_manager
from .synthesizer import SynthesisError, Synthesizer

# Tiers de modele par role (pour la cascade ascendante)
ROLE_TIERS = {
    IterationRole.PRODUCER: "small",
    IterationRole.CRITIC: "medium",
    IterationRole.ADVERSARY: "large",
    IterationRole.ARBITER: "xlarge",
}

# Templates par variante et par role
ROLE_TEMPLATES = {
    Variant.A: {
        IterationRole.PRODUCER: "iteration_1.j2",
        IterationRole.CRITIC: "iteration_2.j2",
        IterationRole.ADVERSARY: "iteration_3.j2",
        IterationRole.ARBITER: "iteration_4.j2",
    },
    Variant.B: {
        IterationRole.PRODUCER: "technical_iteration_1.j2",
        IterationRole.CRITIC: "technical_iteration_2.j2",
        IterationRole.ADVERSARY: "technical_iteration_3.j2",
        IterationRole.ARBITER: "technical_iteration_4.j2",
    },
}

ROLE_LABELS = {
    IterationRole.PRODUCER: "Producteur",
    IterationRole.CRITIC: "Critique",
    IterationRole.ADVERSARY: "Adversaire",
    IterationRole.ARBITER: "Arbitre",
}


class CascadeExecutor:
    """Execute une cascade G.O.A.L. complete."""

    def __init__(
        self,
        provider: BaseProvider,
        prompt_loader: PromptLoader | None = None,
        rag_bridge=None,
    ):
        self.provider = provider
        self.prompt_loader = prompt_loader or PromptLoader()
        self.synthesizer = Synthesizer(self.provider, self.prompt_loader)
        self.rag_bridge = rag_bridge

    def init_state(
        self,
        objective: str,
        variant: Variant = Variant.A,
        audience: str = "",
        constraints: str = "",
    ) -> CascadeState:
        """Cree un nouvel etat de cascade."""
        return CascadeState(
            run_id=uuid.uuid4().hex[:8],
            objective=redact_sensitive(objective),
            variant=variant,
            current_iteration=0,
            max_iterations=5,
        )

    def run(
        self,
        state: CascadeState,
        audience: str = "",
        constraints: str = "",
        verbose: bool = True,
    ) -> CascadeState:
        """Execute la cascade jusqu'au verdict STOP ou la limite."""

        journal = AuditJournal(state.run_id)
        journal.record_event(
            "run_started",
            objective=state.objective,
            variant=state.variant.value,
            provider=self.provider.name,
        )
        state_manager.save_state(state)

        audience = redact_sensitive(audience)
        constraints = redact_sensitive(constraints)

        try:
            state = self._run_loop(state, audience, constraints, verbose, journal)
        except Exception as exc:
            state.status = "failed"
            state.last_error = redact_sensitive(str(exc))
            state_manager.save_state(state)
            journal.record_error(exc)
            raise
        finally:
            state_manager.save_state(state)
            metadata = {
                "objective": state.objective,
                "variant": state.variant.value,
                "provider": self.provider.name,
                "status": state.status,
                "iterations": state.current_iteration,
                "verdict": (
                    state.final_verdict.decision if state.final_verdict else "absent"
                ),
                "last_error": state.last_error or "aucune",
            }
            journal.finalize(metadata)
            if self.rag_bridge is not None:
                try:
                    self.rag_bridge.sync_run(state.run_id, journal=journal)
                except Exception as exc:
                    journal.record_error(exc)
                    journal.refresh_timeline()

        return state

    def _run_loop(
        self,
        state: CascadeState,
        audience: str,
        constraints: str,
        verbose: bool,
        journal: AuditJournal,
    ) -> CascadeState:
        """Exécute la boucle tout en enregistrant chaque entrée et sortie."""

        while state.status == "running":
            # Limite absolue : 5 iterations
            if state.current_iteration >= state.max_iterations:
                state.status = "forced_stop"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification="Limite absolue de 5 iterations atteinte"
                )
                state_manager.save_state(state)
                break

            # Determiner le role de la prochaine iteration
            state.current_iteration += 1
            iteration = state.current_iteration

            # Apres l'iteration 4, on reboucle vers le critique (iteration 5 max)
            if iteration <= 4:
                role = state.role_for_iteration(iteration)
            else:
                role = IterationRole.CRITIC

            if verbose:
                tier = ROLE_TIERS.get(role, "medium")
                label = ROLE_LABELS.get(role, role.value)
                print(f"\n  Iteration {iteration}/{state.max_iterations} "
                      f"-- {label} ({self.provider.name}/{tier}) ...", end=" ", flush=True)

            # Construire le prompt
            prompt = self._build_prompt(state, role, audience, constraints)
            prompt = redact_sensitive(prompt)
            prompt_path = state_manager.save_prompt_output(
                state.run_id, iteration, role.value, prompt
            )
            journal.record_file(
                "prompt_saved",
                prompt_path,
                iteration=iteration,
                role=role.value,
            )

            # Appel LLM
            tier = ROLE_TIERS.get(role, "medium")
            journal.record_event(
                "provider_call_started",
                iteration=iteration,
                role=role.value,
                provider=self.provider.name,
                tier=tier,
            )
            response = self.provider.call(prompt, role=role.value, tier=tier)
            response.text = redact_sensitive(response.text)

            # Enregistrer l'appel
            call_record = LLMCallRecord(
                provider=response.provider,
                model=response.model,
                iteration=iteration,
                role=role.value,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
                raw_output=response.text,
                token_count_estimated=response.token_count_estimated,
            )
            state.history.append(call_record)
            state.accumulated_cost += response.cost_usd

            # Persister la sortie de cette iteration (angle mort identifie)
            iteration_path = state_manager.save_iteration_output(
                state.run_id, iteration, response.text
            )
            journal.record_file(
                "response_saved",
                iteration_path,
                iteration=iteration,
                role=role.value,
            )
            journal.record_event(
                "provider_call_completed",
                iteration=iteration,
                role=role.value,
                provider=response.provider,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                token_count_estimated=response.token_count_estimated,
                latency_ms=response.latency_ms,
                cost_usd=response.cost_usd,
            )

            if verbose:
                cost_str = f"${response.cost_usd:.4f}" if response.cost_usd > 0 else "free"
                print(f"OK  ({cost_str})")

            # Iteration 4 (Arbitre) : parser le verdict
            if role == IterationRole.ARBITER:
                verdict = self._parse_verdict(response.text)
                state.final_verdict = verdict
                if verdict.decision == "STOP":
                    state.status = "stopped"

            # Une cinquieme iteration est la limite absolue. Elle peut
            # analyser le point restant, mais ne declenche jamais un 6e appel.
            if state.current_iteration >= state.max_iterations and state.status == "running":
                state.status = "forced_stop"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification="Limite absolue de 5 iterations atteinte",
                )

            # La synthese est un appel isole entre les iterations principales.
            if role != IterationRole.ARBITER and state.status == "running":
                synthesis_prompt = self.synthesizer.build_prompt(
                    raw_output=response.text,
                    objective=state.objective,
                    iteration_from=iteration,
                    iteration_to=iteration + 1,
                    previous_synthesis=state.last_synthesis,
                )
                synthesis_prompt = redact_sensitive(synthesis_prompt)
                synthesis_prompt_path = state_manager.save_prompt_output(
                    state.run_id,
                    iteration,
                    "synthesizer",
                    synthesis_prompt,
                )
                journal.record_file(
                    "prompt_saved",
                    synthesis_prompt_path,
                    iteration=iteration,
                    role="synthesizer",
                )
                journal.record_event(
                    "provider_call_started",
                    iteration=iteration,
                    role="synthesizer",
                    provider=self.provider.name,
                    tier="small",
                )
                try:
                    synthesis_result = self.synthesizer.process(
                        raw_output=response.text,
                        objective=state.objective,
                        iteration_from=iteration,
                        iteration_to=iteration + 1,
                        previous_synthesis=state.last_synthesis,
                        previous_artifacts=state.artifacts,
                        prompt=synthesis_prompt,
                    )
                except SynthesisError as error:
                    failed_response = error.response
                    if failed_response is not None:
                        failed_response.text = redact_sensitive(failed_response.text)
                        state.history.append(
                            LLMCallRecord(
                                provider=failed_response.provider,
                                model=failed_response.model,
                                iteration=iteration,
                                role="synthesizer",
                                input_tokens=failed_response.input_tokens,
                                output_tokens=failed_response.output_tokens,
                                cost_usd=failed_response.cost_usd,
                                latency_ms=failed_response.latency_ms,
                                raw_output=failed_response.text,
                                token_count_estimated=(
                                    failed_response.token_count_estimated
                                ),
                            )
                        )
                        state.accumulated_cost += failed_response.cost_usd
                        failed_path = state_manager.save_synthesis_output(
                            state.run_id,
                            iteration,
                            failed_response.text,
                        )
                        journal.record_file(
                            "response_saved",
                            failed_path,
                            iteration=iteration,
                            role="synthesizer",
                        )
                        journal.record_event(
                            "provider_call_completed",
                            iteration=iteration,
                            role="synthesizer",
                            provider=failed_response.provider,
                            model=failed_response.model,
                            parse_status="invalid",
                        )
                    raise
                synthesis_response = synthesis_result.response
                synthesis_response.text = redact_sensitive(synthesis_response.text)
                state.history.append(
                    LLMCallRecord(
                        provider=synthesis_response.provider,
                        model=synthesis_response.model,
                        iteration=iteration,
                        role="synthesizer",
                        input_tokens=synthesis_response.input_tokens,
                        output_tokens=synthesis_response.output_tokens,
                        cost_usd=synthesis_response.cost_usd,
                        latency_ms=synthesis_response.latency_ms,
                        raw_output=synthesis_response.text,
                        token_count_estimated=synthesis_response.token_count_estimated,
                    )
                )
                state.accumulated_cost += synthesis_response.cost_usd
                state.last_synthesis = synthesis_result.synthesis
                state.artifacts = synthesis_result.artifacts
                synthesis_path = state_manager.save_synthesis_output(
                    state.run_id,
                    iteration,
                    synthesis_response.text,
                )
                journal.record_file(
                    "response_saved",
                    synthesis_path,
                    iteration=iteration,
                    role="synthesizer",
                )
                journal.record_event(
                    "provider_call_completed",
                    iteration=iteration,
                    role="synthesizer",
                    provider=synthesis_response.provider,
                    model=synthesis_response.model,
                    input_tokens=synthesis_response.input_tokens,
                    output_tokens=synthesis_response.output_tokens,
                    token_count_estimated=synthesis_response.token_count_estimated,
                    latency_ms=synthesis_response.latency_ms,
                    cost_usd=synthesis_response.cost_usd,
                )

                if verbose:
                    print("  Synthese orientee objectif -- OK")

            # Sauvegarder l'etat a chaque iteration (checkpointing)
            state_manager.save_state(state)

        # Sauvegarder le livrable final
        if state.history:
            arbiter_outputs = [
                call.raw_output for call in state.history if call.role == "arbiter"
            ]
            main_outputs = [
                call.raw_output for call in state.history if call.role != "synthesizer"
            ]
            final_output = (
                arbiter_outputs[-1] if arbiter_outputs else main_outputs[-1]
            )
            final_path = state_manager.save_final_output(state.run_id, final_output)
            journal.record_file("final_output_saved", final_path)

        # Persister aussi les transitions terminales survenues hors iteration.
        state_manager.save_state(state)

        return state

    def _build_prompt(
        self,
        state: CascadeState,
        role: IterationRole,
        audience: str = "",
        constraints: str = "",
    ) -> str:
        """Construit le prompt pour une iteration donnee."""
        template_name = ROLE_TEMPLATES[state.variant].get(role, "iteration_1.j2")

        # Contexte precedent :
        # - Pour l'arbitre (iteration 4) : tout l'historique cumule
        # - Pour les autres : uniquement la derniere sortie
        previous_output = ""
        if state.history:
            if role == IterationRole.ARBITER:
                # L'arbitre voit tout le travail cumule
                previous_output = "\n\n---\n\n".join(
                    f"[Iteration {h.iteration} — {h.role}]\n{h.raw_output}"
                    for h in state.history
                )
            else:
                previous_output = state.history[-1].raw_output

        last_synthesis = ""
        if state.last_synthesis:
            last_synthesis = state.last_synthesis.model_dump_json(indent=2)

        artifacts = ""
        if state.artifacts:
            blocks = []
            for artifact in state.artifacts:
                language = artifact.language or "text"
                blocks.append(f"```{language}\n{artifact.content}\n```")
            artifacts = "\n\n".join(blocks)

        return self.prompt_loader.render(
            template_name,
            objective=state.objective,
            previous_output=previous_output,
            last_synthesis=last_synthesis,
            audience=audience,
            constraints=constraints,
            artifacts=artifacts,
        )

    def _parse_verdict(self, text: str) -> Verdict:
        """Extrait le verdict (STOP/CONTINUE) du texte de l'arbitre."""
        matches = list(
            re.finditer(
                r"^\s*VERDICT\s*:\s*(STOP|CONTINUE)\b",
                text,
                re.IGNORECASE | re.MULTILINE,
            )
        )
        if not matches:
            raise ValueError(
                "Verdict invalide : ligne 'VERDICT : STOP|CONTINUE' absente"
            )
        decision = matches[-1].group(1).upper()

        just_match = re.search(
            r"^\s*JUSTIFICATION\s*:\s*(.+)$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        justification = (
            just_match.group(1).strip()[:500]
            if just_match
            else "Verdict explicite rendu par l'arbitre"
        )

        return Verdict(
            decision=decision,
            justification=justification,
        )
