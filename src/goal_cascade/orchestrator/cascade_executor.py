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

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from ..audit_journal import AuditJournal, redact_sensitive
from ..prompts import PromptLoader
from ..providers.base import BaseProvider
from ..schemas.models import (
    CascadeState,
    GoalOrientedSynthesis,
    IterationRole,
    LLMCallRecord,
    RunReceipt,
    Verdict,
    Variant,
)
from . import state_manager
from .budget_tracker import BudgetTracker
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
        synthesizer_provider: BaseProvider,
        prompt_loader: PromptLoader | None = None,
        rag_bridge=None,
        budget_tracker: BudgetTracker | None = None,
    ):
        if synthesizer_provider is provider:
            raise ValueError(
                "Le synthétiseur exige une instance de provider distincte"
            )
        self.provider = provider
        self.synthesizer_provider = synthesizer_provider
        self.prompt_loader = prompt_loader or PromptLoader()
        self.synthesizer = Synthesizer(
            self.synthesizer_provider,
            self.prompt_loader,
        )
        self.rag_bridge = rag_bridge
        self._budget = budget_tracker

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
        no_synth: bool = False,
    ) -> CascadeState:
        """Execute la cascade jusqu'au verdict STOP ou la limite."""

        journal = AuditJournal(state.run_id)
        start_time = datetime.now()
        journal.record_event(
            "run_started",
            objective=state.objective,
            variant=state.variant.value,
            provider=self.provider.name,
            synthesizer_provider=self.synthesizer_provider.name,
            no_synth=no_synth,
        )
        state_manager.save_state(state)

        audience = redact_sensitive(audience)
        constraints = redact_sensitive(constraints)

        try:
            state = self._run_with_graph(state, audience, constraints, verbose, journal, no_synth=no_synth)
        except Exception as exc:
            state.status = "failed"
            state.last_error = redact_sensitive(str(exc))
            state_manager.save_state(state)
            journal.record_error(exc)
            raise
        finally:
            state_manager.save_state(state)
            duration_s = (datetime.now() - start_time).total_seconds()
            metadata = {
                "objective": state.objective,
                "variant": state.variant.value,
                "provider": self.provider.name,
                "synthesizer_provider": self.synthesizer_provider.name,
                "status": state.status,
                "iterations": state.current_iteration,
                "verdict": (
                    state.final_verdict.decision if state.final_verdict else "absent"
                ),
                "last_error": state.last_error or "aucune",
            }
            journal.finalize(metadata)
            try:
                receipt = self.build_receipt(state, duration_s)
                receipt_path = state_manager.save_receipt(state.run_id, receipt)
                journal.record_file("receipt_saved", receipt_path)
                journal.refresh_timeline()
            except Exception as exc:
                journal.record_error(exc)
                journal.refresh_timeline()
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
        no_synth: bool = False,
        _single_iteration: bool = False,
    ) -> CascadeState:
        """Exécute la boucle tout en enregistrant chaque entrée et sortie.

        Si _single_iteration=True, exécute exactement une itération et retourne.
        Utilisé par le graphe LangGraph pour le checkpointing par itération.
        """

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

            # Kill switch budgetaire (section 9 du plan v2)
            if self._budget is not None and self._budget.is_exceeded(state.run_id, state.accumulated_cost):
                state.status = "budget_exceeded"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification=(
                        f"Budget depasse: ${state.accumulated_cost:.4f} "
                        f"(max ${self._budget.config.max_per_run_usd:.2f})"
                    ),
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
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
            )
            state.history.append(call_record)
            state.accumulated_cost += response.cost_usd
            if self._budget is not None:
                self._budget.record(response.cost_usd)

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
                else:
                    # CONTINUE : injecter la justification de l'arbitre
                    # dans last_synthesis pour que l'itération 5 la reçoive.
                    state.last_synthesis = GoalOrientedSynthesis(
                        objective=state.objective,
                        key_decisions=(
                            state.last_synthesis.key_decisions
                            if state.last_synthesis
                            else ["Synthèse arbitre"]
                        ),
                        uncertainties=(
                            state.last_synthesis.uncertainties
                            if state.last_synthesis
                            else []
                        ),
                        next_instruction=verdict.justification,
                        iteration_from=4,
                        iteration_to=5,
                    )

            # Une cinquieme iteration est la limite absolue. Elle peut
            # analyser le point restant, mais ne declenche jamais un 6e appel.
            if state.current_iteration >= state.max_iterations and state.status == "running":
                state.status = "forced_stop"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification="Limite absolue de 5 iterations atteinte",
                )

            # La synthese est un appel isole entre les iterations principales.
            # En mode --no-synth, on passe la sortie brute a l'iteration suivante
            # sans filtrage. Utile pour debugger une synthese qui ecrase des
            # informations critiques.
            if (
                role != IterationRole.ARBITER
                and state.status == "running"
                and not no_synth
            ):
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
                    provider=self.synthesizer_provider.name,
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
                                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                            )
                        )
                        state.accumulated_cost += failed_response.cost_usd
                        if self._budget is not None:
                            self._budget.record(failed_response.cost_usd)
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
                        timestamp_utc=datetime.now(timezone.utc).isoformat(),
                    )
                )
                state.accumulated_cost += synthesis_response.cost_usd
                if self._budget is not None:
                    self._budget.record(synthesis_response.cost_usd)
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

                # 🆕 DRIFT — STOP anticipé si dérive critique (section 6.1 + 11.3)
                if synthesis_result.drift_status.value == "critical":
                    state.status = "forced_stop"
                    state.final_verdict = Verdict(
                        decision="STOP",
                        justification=(
                            f"Dérive détectée (sim={synthesis_result.similarity_score:.3f})"
                        ),
                    )
                    journal.record_event(
                        "drift_forced_stop",
                        iteration=iteration,
                        similarity=synthesis_result.similarity_score,
                        drift_status=synthesis_result.drift_status.value,
                    )
                    state_manager.save_state(state)
                    break

            # Sauvegarder l'etat a chaque iteration (checkpointing)
            state_manager.save_state(state)

            # En mode single_iteration (graphe LangGraph), on s'arrête
            # après chaque itération pour laisser le graphe gérer la boucle.
            if _single_iteration:
                break

        # Sauvegarder le livrable final
        if state.history:
            main_outputs = [
                call.raw_output for call in state.history if call.role != "synthesizer"
            ]
            if state.current_iteration > 4:
                # L'itération 5 a tourné : sa sortie prime sur l'arbitre.
                final_output = main_outputs[-1]
            else:
                arbiter_outputs = [
                    call.raw_output
                    for call in state.history
                    if call.role == "arbiter"
                ]
                final_output = (
                    arbiter_outputs[-1] if arbiter_outputs else main_outputs[-1]
                )
            final_path = state_manager.save_final_output(state.run_id, final_output)
            journal.record_file("final_output_saved", final_path)

        # Persister aussi les transitions terminales survenues hors iteration.
        state_manager.save_state(state)

        return state

    def _run_with_graph(
        self,
        state: CascadeState,
        audience: str,
        constraints: str,
        verbose: bool,
        journal: AuditJournal,
        no_synth: bool = False,
    ) -> CascadeState:
        """Exécute la cascade via un graphe LangGraph avec checkpointing SQLite.

        Le graphe a un nœud "iteration" qui appelle _run_loop en mode
        _single_iteration. Le checkpoint SQLite sauvegarde l'état à chaque
        transition de nœud, permettant goal resume.
        """
        from .cascade_graph import build_cascade_graph, compile_with_sqlite

        run_dir = state_manager.get_run_dir(state.run_id)
        checkpoint_dir = run_dir / ".checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_path = checkpoint_dir / "checkpoint.db"

        # Fonction nœud : encapsule une itération de la cascade.
        # Capture self, audience, constraints, verbose, no_synth, journal
        # via closure.
        def iteration_node(graph_state: dict) -> dict:
            # Désérialiser le CascadeState depuis le dict du graphe
            cascade_dict = graph_state.get("cascade", {})
            if cascade_dict:
                current_state = CascadeState(**cascade_dict)
            else:
                current_state = state

            # Exécuter une itération
            self._run_loop(
                current_state,
                audience=audience,
                constraints=constraints,
                verbose=verbose,
                journal=journal,
                no_synth=no_synth,
                _single_iteration=True,
            )

            # Sérialiser et retourner la mise à jour
            return {
                "cascade": current_state.model_dump(),
                "current_iteration": current_state.current_iteration,
                "status": current_state.status,
            }

        # Construire et compiler le graphe avec checkpointer SQLite
        graph = build_cascade_graph(iteration_node)
        app, checkpointer = compile_with_sqlite(graph, checkpoint_path)

        # État initial du graphe
        initial_graph_state = {
            "cascade": state.model_dump(),
            "run_id": state.run_id,
            "current_iteration": state.current_iteration,
            "status": state.status,
        }
        config = {"configurable": {"thread_id": state.run_id}}

        result = app.invoke(initial_graph_state, config)

        # Mettre à jour l'état depuis le résultat final du graphe
        final_cascade = result.get("cascade", {})
        if final_cascade:
            final_state = CascadeState(**final_cascade)
            state.status = final_state.status
            state.current_iteration = final_state.current_iteration
            state.history = final_state.history
            state.accumulated_cost = final_state.accumulated_cost
            state.last_synthesis = final_state.last_synthesis
            state.artifacts = final_state.artifacts
            state.final_verdict = final_state.final_verdict

        return state

    def resume(
        self,
        run_id: str,
        audience: str = "",
        constraints: str = "",
        verbose: bool = True,
        no_synth: bool = False,
    ) -> CascadeState:
        """Reprend une cascade interrompue depuis le dernier checkpoint SQLite.

        Charge le checkpoint pour le run_id donné et ré-invocque le graphe
        LangGraph pour continuer l'exécution.
        """
        from .cascade_graph import build_cascade_graph, compile_with_sqlite

        run_dir = state_manager.get_run_dir(run_id)
        checkpoint_dir = run_dir / ".checkpoints"
        checkpoint_path = checkpoint_dir / "checkpoint.db"

        if not checkpoint_path.exists():
            raise FileNotFoundError(
                f"Aucun checkpoint trouvé pour le run {run_id} : {checkpoint_path}"
            )

        # Charger l'état depuis le checkpoint
        def dummy_node(graph_state: dict) -> dict:
            return graph_state

        graph = build_cascade_graph(dummy_node)
        app, checkpointer = compile_with_sqlite(graph, checkpoint_path)

        config = {"configurable": {"thread_id": run_id}}

        saved = app.get_state(config)

        if not saved or not saved.values:
            raise FileNotFoundError(
                f"Checkpoint vide pour le run {run_id}"
            )

        checkpointed = saved.values
        cascade_dict = checkpointed.get("cascade", {})
        if not cascade_dict:
            raise FileNotFoundError(
                f"Pas de CascadeState dans le checkpoint du run {run_id}"
            )

        state = CascadeState(**cascade_dict)
        journal = AuditJournal(run_id)

        # Relancer avec le vrai graphe
        return self._run_with_graph(state, audience, constraints, verbose, journal, no_synth=no_synth)

    def _build_prompt(
        self,
        state: CascadeState,
        role: IterationRole,
        audience: str = "",
        constraints: str = "",
    ) -> str:
        """Construit le prompt pour une iteration donnee."""
        template_name = ROLE_TEMPLATES[state.variant].get(role, "iteration_1.j2")

        # L'arbitre ne reçoit jamais les sorties brutes : uniquement la
        # synthèse consolidée et les artefacts immuables rendus ci-dessous.
        previous_output = ""
        if state.history and role != IterationRole.ARBITER:
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
        """Valide l'objet JSON terminal conforme au schéma Verdict."""
        stripped = text.rstrip()
        if not stripped:
            raise ValueError("Verdict JSON invalide ou absent")

        try:
            if stripped.endswith("```"):
                closing_fence = len(stripped) - 3
                opening_fence = stripped.lower().rfind(
                    "```json",
                    0,
                    closing_fence,
                )
                if opening_fence == -1:
                    raise ValueError("Bloc JSON terminal absent")
                candidate = stripped[opening_fence + len("```json") : closing_fence]
                data = json.loads(candidate.strip())
            else:
                decoder = json.JSONDecoder()
                decoded: list[tuple[object, int]] = []
                cursor = 0
                while cursor < len(stripped):
                    start = stripped.find("{", cursor)
                    if start == -1:
                        break
                    try:
                        value, consumed = decoder.raw_decode(stripped[start:])
                    except json.JSONDecodeError:
                        cursor = start + 1
                        continue
                    end = start + consumed
                    decoded.append((value, end))
                    cursor = end

                if not decoded:
                    raise ValueError("Objet JSON terminal absent")
                data, end = decoded[-1]
                if stripped[end:].strip():
                    raise ValueError("Texte présent après le verdict JSON")

            return Verdict.model_validate(data)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith("Verdict JSON"):
                raise
            try:
                details = str(exc)
            except Exception:
                details = type(exc).__name__
            raise ValueError(f"Verdict JSON invalide ou absent : {details}") from exc

    def build_receipt(self, state: CascadeState, duration_s: float) -> RunReceipt:
        """Construit le RunReceipt depuis l'etat final de la cascade.

        Délègue la construction à RunReceipt.from_calls() qui calcule
        automatiquement total_cost, cache_hit_rate et projected_monthly_cost.
        """
        runs_per_day = (
            self._budget.config.runs_per_day_projection
            if self._budget is not None
            else 10
        )
        return RunReceipt.from_calls(
            run_id=state.run_id,
            objective=state.objective,
            verdict=(
                state.final_verdict.decision
                if state.final_verdict else "absent"
            ),
            duration_s=duration_s,
            calls=list(state.history),
            runs_per_day=runs_per_day,
        )
