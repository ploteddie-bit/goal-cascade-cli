"""Graphe LangGraph pour la cascade G.O.A.L. unique.

Architecture à 6 nœuds séparés conformes à la spec V2 §6 :
    INIT → PRODUCER → SYNTH → CRITIC → SYNTH → ADVERSARY → SYNTH → ARBITER → VERDICT
                                                                              │
                                                              ┌───────────────┴───────────────┐
                                                              │                               │
                                                         STOP ✅                         CONTINUE ↩️
                                                                                      (max 5, puis forced_stop)

Chaque nœud reçoit le CascadeState et retourne un dict partiel
(mise à jour). Les edges conditionnelles vérifient le budget, la
dérive et la limite d'itérations.

Checkpointing : SqliteSaver stocke l'état à chaque transition.
goal resume invoque le même graph avec le même thread_id.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from ..audit_journal import AuditJournal, redact_sensitive
from ..orchestrator import state_manager
from ..schemas.models import (
    CascadeState,
    IterationRole,
    LLMCallRecord,
    Verdict,
)
from .budget_tracker import BudgetExceeded, BudgetTracker
from .drift_detector import DriftDetector, DriftStatus

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# ── Mapping rôle → tier ────────────────────────────────────────

ROLE_TIERS = {
    IterationRole.PRODUCER: "small",
    IterationRole.CRITIC: "medium",
    IterationRole.ADVERSARY: "large",
    IterationRole.ARBITER: "xlarge",
}

ROLE_LABELS = {
    IterationRole.PRODUCER: "Producteur",
    IterationRole.CRITIC: "Critique",
    IterationRole.ADVERSARY: "Adversaire",
    IterationRole.ARBITER: "Arbitre",
}


# ── Classe principale ──────────────────────────────────────────


class CascadeGraph:
    """State machine LangGraph pour une cascade G.O.A.L. unique.

    Chaque nœud est une fonction qui prend un CascadeState et retourne
    un dict partiel (pas de mutation directe du state).

    Le journal d'audit est optionnel : s'il est fourni, chaque
    transition est enregistrée (prompt, response, événements).
    """

    def __init__(
        self,
        provider: Any,
        synthesizer_provider: Any,
        synthesizer: Any,
        budget_tracker: BudgetTracker | None = None,
        drift_detector: DriftDetector | None = None,
        prompt_loader: Any = None,
        journal: AuditJournal | None = None,
        cicd_hook: Any = None,
        audience: str = "",
        constraints: str = "",
        no_synth: bool = False,
        prompt_resolver: Any = None,
    ):
        self.provider = provider
        self.synthesizer_provider = synthesizer_provider
        self.synthesizer = synthesizer
        self._budget = budget_tracker
        self._drift = drift_detector
        self._prompt_loader = prompt_loader
        self._journal = journal
        self._cicd = cicd_hook  # si None, CICDCheck no-op par défaut
        self._audience = audience
        self._constraints = constraints
        self._no_synth = no_synth
        # O4 : support des overrides par run (injecté par CascadeExecutor)
        self._prompt_resolver = prompt_resolver

    def _build_graph(self) -> Any:
        """Construit le graphe d'états G.O.A.L. à 6 nœuds."""
        graph = StateGraph(CascadeState)

        # Nœuds
        graph.add_node("producer", self._node_producer)
        graph.add_node("synth", self._node_synth)
        graph.add_node("critic", self._node_critic)
        graph.add_node("adversary", self._node_adversary)
        graph.add_node("arbiter", self._node_arbiter)
        graph.add_node("verdict", self._node_verdict)

        # Point d'entrée
        graph.set_entry_point("producer")

        # Edges linéaires
        graph.add_edge("producer", "synth")
        graph.add_edge("critic", "synth")
        graph.add_edge("adversary", "synth")
        graph.add_edge("arbiter", "verdict")

        # Edge conditionnelle après synth
        graph.add_conditional_edges(
            "synth",
            self._route_after_synth,
            {
                "critic": "critic",
                "adversary": "adversary",
                "arbiter": "arbiter",
                "forced_stop": END,
            },
        )

        # Edge conditionnelle après verdict
        graph.add_conditional_edges(
            "verdict",
            self._route_after_verdict,
            {
                "stop": END,
                "continue": "critic",
                "forced_stop": END,
            },
        )

        return graph

    def compile_with_sqlite(self, db_path: Path | str) -> Any:
        """Compile le graphe avec checkpointing SQLite.

        Q1 : la connexion SQLite est stockée sur l'instance pour pouvoir
        être fermée proprement quand le graph n'est plus nécessaire.
        Sans ce stockage, les connexions restent ouvertes indéfiniment,
        verrouillant le fichier et consommant des descripteurs.

        Returns:
            Tuple (graph_compiled, checkpointer). Le caller doit
            fermer la connexion via ``graph_instance.close_sqlite()``
            quand la cascade est terminée.
        """
        graph = self._build_graph()
        self._sqlite_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        checkpointer = SqliteSaver(self._sqlite_conn)
        return graph.compile(checkpointer=checkpointer), checkpointer

    def close_sqlite(self) -> None:
        """Ferme proprement la connexion SQLite (Q1 — fuite de connexion).

        À appeler après chaque cascade terminée, avant de détruire
        l'instance CascadeGraph.
        """
        if hasattr(self, "_sqlite_conn") and self._sqlite_conn is not None:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass
            self._sqlite_conn = None

    # ── Helper : exécution d'une itération complète ────────────

    def _execute_iteration(
        self,
        cascade: CascadeState,
        role: IterationRole,
        iteration: int,
        tier: str,
    ) -> dict[str, Any]:
        """Exécute une itération : prompt → appel LLM → journal → persistance.

        Centralise la logique commune aux 4 nœuds d'itération (producer,
        critic, adversary, arbiter). Chaque nœud ne fait qu'appeler ce
        helper avec son rôle/tier/numéro d'itération.
        """
        role_value = role.value

        # 1. Construire et persister le prompt
        prompt = self._build_prompt(cascade, role)
        prompt = redact_sensitive(prompt)
        prompt_path = state_manager.save_prompt_output(
            cascade.run_id, iteration, role_value, prompt
        )
        if self._journal:
            self._journal.record_file(
                "prompt_saved",
                prompt_path,
                iteration=iteration,
                role=role_value,
            )
            self._journal.record_event(
                "provider_call_started",
                iteration=iteration,
                role=role_value,
                provider=self.provider.name,
                tier=tier,
            )

        # 2. Appel LLM
        response = self.provider.call(prompt, role=role_value, tier=tier)
        response.text = redact_sensitive(response.text)

        # 3. Construire le record d'appel
        call_record = LLMCallRecord(
            provider=response.provider,
            model=response.model,
            iteration=iteration,
            role=role_value,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            raw_output=response.text,
            token_count_estimated=response.token_count_estimated,
            timestamp_utc=datetime.now(UTC).isoformat(),
        )

        # 4. Persister la sortie brute
        response_path = state_manager.save_iteration_output(
            cascade.run_id, iteration, response.text
        )
        if self._journal:
            self._journal.record_file(
                "response_saved",
                response_path,
                iteration=iteration,
                role=role_value,
            )
            self._journal.record_event(
                "provider_call_completed",
                iteration=iteration,
                role=role_value,
                provider=response.provider,
                model=response.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
                token_count_estimated=response.token_count_estimated,
            )

        # 5. Budget tracking
        if self._budget is not None:
            self._budget.record(response.cost_usd)

        # 6. Update state — append au history existant
        new_history = list(cascade.history) + [call_record]
        return {
            "current_iteration": iteration,
            "history": new_history,
            "accumulated_cost": cascade.accumulated_cost + response.cost_usd,
            "last_raw_output": response.text,
        }

    # ── Nœuds ──────────────────────────────────────────────────

    def _node_producer(self, state: Any) -> dict[str, Any]:
        """Itération 1 : Producteur (petit modèle)."""
        cascade = self._coerce_state(state)
        return self._execute_iteration(cascade, IterationRole.PRODUCER, 1, "small")

    def _node_critic(self, state: Any) -> dict[str, Any]:
        """Itération 2 (ou 5 si CONTINUE) : Critique (modèle moyen)."""
        cascade = self._coerce_state(state)
        iteration = cascade.current_iteration + 1
        return self._execute_iteration(cascade, IterationRole.CRITIC, iteration, "medium")

    def _node_adversary(self, state: Any) -> dict[str, Any]:
        """Itération 3 : Adversaire (grand modèle)."""
        cascade = self._coerce_state(state)
        iteration = cascade.current_iteration + 1
        return self._execute_iteration(cascade, IterationRole.ADVERSARY, iteration, "large")

    def _node_arbiter(self, state: Any) -> dict[str, Any]:
        """Itération 4 : Arbitre (très grand modèle)."""
        cascade = self._coerce_state(state)
        iteration = cascade.current_iteration + 1
        return self._execute_iteration(cascade, IterationRole.ARBITER, iteration, "xlarge")

    def _node_synth(self, state: Any) -> dict[str, Any]:
        """Synthèse orientée objectif + détection de dérive + CICD.

        En mode --no-synth, ce nœud devient un no-op : la sortie brute
        est passée telle quelle à l'itération suivante (utile pour
        debug quand une synthèse écrase des informations critiques).

        Si on a atteint la limite d'itérations (typiquement après le
        5e passage en synth suite à un verdict CONTINUE), on force
        status='forced_stop' + verdict STOP. Sans ce hook, la cascade
        LangGraph sortirait sur END avec status='running' car les
        conditional edges seules ne modifient pas le state.
        """
        # Mode --no-synth : pas de synthèse, on retourne juste un pass-through.
        if self._no_synth:
            return {}

        cascade = self._coerce_state(state)

        # Garde-fou limite d'itérations : si on est au max, forcer le STOP.
        if cascade.current_iteration >= cascade.max_iterations:
            logger.warning(
                "iteration_limit_reached iteration=%d max=%d action=forced_stop",
                cascade.current_iteration,
                cascade.max_iterations,
            )
            return {
                "status": "forced_stop",
                "final_verdict": Verdict(
                    decision="STOP",
                    justification="Limite absolue de 5 itérations atteinte",
                ),
            }

        # Récupérer la sortie brute du dernier appel
        if isinstance(state, dict):
            raw_output = state.get("last_raw_output", "")
        else:
            raw_output = cascade.history[-1].raw_output if cascade.history else ""

        iteration = cascade.current_iteration

        # 1. Construire et persister le prompt de synthèse
        synth_prompt = self._build_synth_prompt(cascade, raw_output, iteration)
        synth_prompt = redact_sensitive(synth_prompt)
        synth_prompt_path = state_manager.save_prompt_output(
            cascade.run_id, iteration, "synthesizer", synth_prompt
        )
        if self._journal:
            self._journal.record_file(
                "prompt_saved",
                synth_prompt_path,
                iteration=iteration,
                role="synthesizer",
            )
            self._journal.record_event(
                "provider_call_started",
                iteration=iteration,
                role="synthesizer",
                provider=self.synthesizer_provider.name,
                tier="small",
            )

        # 2. Appeler le synthétiseur
        from .synthesizer import SynthesisError

        try:
            result = self.synthesizer.process(
                raw_output=raw_output,
                objective=cascade.objective,
                iteration_from=iteration,
                iteration_to=iteration + 1,
                previous_synthesis=cascade.last_synthesis,
                previous_artifacts=cascade.artifacts,
                prompt=synth_prompt,
            )
        except SynthesisError as error:
            # Sauver la réponse invalide avant de propager l'erreur
            failed_response = error.response
            if failed_response is not None:
                failed_response.text = redact_sensitive(failed_response.text)
                failed_path = state_manager.save_synthesis_output(
                    cascade.run_id, iteration, failed_response.text
                )
                if self._journal:
                    self._journal.record_file(
                        "response_saved",
                        failed_path,
                        iteration=iteration,
                        role="synthesizer",
                    )
                    self._journal.record_event(
                        "provider_call_completed",
                        iteration=iteration,
                        role="synthesizer",
                        provider=failed_response.provider,
                        model=failed_response.model,
                        parse_status="invalid",
                    )
            raise
        except Exception as exc:
            logger.error(
                "synth_failed iteration=%d error=%s",
                iteration,
                redact_sensitive(str(exc)),
            )
            return {"last_synthesis": None, "artifacts": cascade.artifacts}

        # 3. Sauver la synthèse valide
        synth_response = result.response
        synth_response.text = redact_sensitive(synth_response.text)
        synthesis_path = state_manager.save_synthesis_output(
            cascade.run_id, iteration, synth_response.text
        )
        if self._journal:
            self._journal.record_file(
                "response_saved",
                synthesis_path,
                iteration=iteration,
                role="synthesizer",
            )
            self._journal.record_event(
                "provider_call_completed",
                iteration=iteration,
                role="synthesizer",
                provider=synth_response.provider,
                model=synth_response.model,
                input_tokens=synth_response.input_tokens,
                output_tokens=synth_response.output_tokens,
                cost_usd=synth_response.cost_usd,
                latency_ms=synth_response.latency_ms,
                token_count_estimated=synth_response.token_count_estimated,
            )

        # 4. Budget tracking
        if self._budget is not None:
            self._budget.record(synth_response.cost_usd)

        # 5. Mise à jour state
        updates: dict[str, Any] = {
            "artifacts": result.artifacts,
            "last_synthesis": result.synthesis,
            "coverage_score": getattr(result, "coverage_score", None),
        }

        # 6. Détection de dérive
        if result.drift_status == DriftStatus.CRITICAL:
            logger.warning(
                "drift_critical similarity=%.4f iteration=%d",
                result.similarity_score or 0.0,
                iteration,
            )
            updates["status"] = "forced_stop"
            updates["final_verdict"] = Verdict(
                decision="STOP",
                justification=f"Dérive détectée (sim={result.similarity_score:.3f})",
            )
        elif result.drift_status == DriftStatus.WARNING:
            logger.info(
                "drift_warning similarity=%.4f iteration=%d",
                result.similarity_score or 0.0,
                iteration,
            )

        # 7. Vérification CICD déterministe (info, non bloquante)
        if result.artifacts:
            self._run_cicd_checks(result.artifacts, iteration)

        return updates

    def _node_verdict(self, state: Any) -> dict[str, Any]:
        """Parse le verdict de l'arbitre.

        Doute profite au STOP : si le parsing échoue, on retourne un
        verdict STOP par défaut et status='stopped' plutôt que de
        propager l'exception (le caller appliquerait la règle F4).
        """
        cascade = self._coerce_state(state)
        if isinstance(state, dict):
            raw_output = state.get("last_raw_output", "")
        else:
            raw_output = cascade.history[-1].raw_output if cascade.history else ""

        try:
            verdict = self._parse_verdict_strict(raw_output)
        except ValueError as exc:
            # Verdict non parsable → STOP par défaut (doute profite au STOP)
            if self._journal:
                self._journal.record_event(
                    "verdict_parse_failed",
                    error=redact_sensitive(str(exc)),
                    action="default_to_STOP",
                )
            verdict = Verdict(
                decision="STOP",
                justification="Verdict non parsable, STOP par défaut",
            )

        updates: dict[str, Any] = {"final_verdict": verdict}

        if verdict.decision == "STOP":
            updates["status"] = "stopped"
        else:
            # CONTINUE — vérifier la limite absolue
            if cascade.current_iteration >= cascade.max_iterations:
                updates["status"] = "forced_stop"
                updates["final_verdict"] = Verdict(
                    decision="STOP",
                    justification="Limite absolue de 5 itérations atteinte",
                )

        return updates

    # ── Routing conditionnel ───────────────────────────────────

    def _route_after_synth(self, state: Any) -> str:
        """Route après synthèse : vérifie budget + dérive + itération."""
        cascade = self._coerce_state(state)

        # Dérive critique → STOP forcé
        if cascade.status == "forced_stop":
            return "forced_stop"

        # Budget check AVANT la prochaine itération
        if self._budget is not None:
            try:
                self._budget.check_budget(cascade.run_id, cascade.accumulated_cost)
            except BudgetExceeded as exc:
                logger.error(
                    "budget_exceeded run=%s error=%s",
                    cascade.run_id,
                    redact_sensitive(str(exc)),
                )
                return "forced_stop"

        # Router vers le prochain rôle selon l'itération courante
        current = cascade.current_iteration
        return {1: "critic", 2: "adversary", 3: "arbiter"}.get(current, "forced_stop")

    def _route_after_verdict(self, state: Any) -> str:
        """Route après verdict : STOP ou CONTINUE (max 5)."""
        cascade = self._coerce_state(state)

        if cascade.status in ("forced_stop", "budget_exceeded"):
            return "forced_stop"

        if cascade.final_verdict and cascade.final_verdict.decision == "STOP":
            return "stop"

        # CONTINUE — reboucler vers critic si < max_iterations
        if cascade.current_iteration < cascade.max_iterations:
            logger.info(
                "continue_loop iteration=%d max=%d",
                cascade.current_iteration,
                cascade.max_iterations,
            )
            return "continue"

        # Limite atteinte
        return "forced_stop"

    # ── Helpers ────────────────────────────────────────────────

    # ── Helpers synth / CICD ───────────────────────────────────

    def _build_synth_prompt(
        self,
        cascade: CascadeState,
        raw_output: str,
        iteration: int,
    ) -> str:
        """Construit le prompt de synthèse (audit + persistance avant appel)."""
        return self.synthesizer.build_prompt(
            raw_output=raw_output,
            objective=cascade.objective,
            iteration_from=iteration,
            iteration_to=iteration + 1,
            previous_synthesis=cascade.last_synthesis,
        )

    def _run_cicd_checks(
        self,
        artifacts: list,
        iteration: int,
    ) -> Any:
        """Exécute le hook CI/CD déterministe sur les artefacts synthétisés.

        Mode informatif : un échec n'arrête PAS la cascade, il est tracé
        dans le journal pour auditabilité (cf. cahier A1-A6).
        """
        from .cicd_hook import InterfaceContract

        contract = InterfaceContract(
            contract_id=f"cicd-{iteration}-{hash(tuple(a.checksum for a in artifacts)) & 0xFFFFFF:06x}",
            producer_module="cascade",
            consumer_module="cascade",
            output_description="auto-detect",
            input_description="auto-detect",
            exchange_format="auto",
        )
        result = self._cicd.run_deterministic_checks(contract, list(artifacts))
        if self._journal:
            self._journal.record_event(
                "cicd_checks",
                iteration=iteration,
                passed=result.passed,
                artifacts=len(artifacts),
                failures=len(result.failures),
            )
        if not result.passed:
            logger.warning(
                "cicd_artifacts_non_compliant iteration=%d failures=%d action=continue_with_artifacts",
                iteration,
                len(result.failures),
            )
        return result

    @staticmethod
    def _coerce_state(state: Any) -> CascadeState:
        """Accepte soit un CascadeState, soit un dict sérialisable."""
        if isinstance(state, CascadeState):
            return state
        if isinstance(state, dict):
            return CascadeState.model_validate(state)
        raise TypeError(f"Type de state non supporté : {type(state).__name__}")

    def _build_prompt(self, state: CascadeState, role: IterationRole) -> str:
        """Construit le prompt pour un rôle donné.

        O4 : si un prompt_resolver est injecté, vérifie d'abord
        l'override du run dans ~/.goal/runs/{run_id}/prompts/.
        """
        if self._prompt_loader is None:
            return f"Role: {role.value}\nObjective: {state.objective}"

        from ..schemas.models import Variant

        template_name = {
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
        }.get(state.variant, {}).get(role, "iteration_1.j2")

        # O4 : chercher un override du prompt pour ce run spécifique
        override_source = None
        if self._prompt_resolver is not None:
            try:
                override_source = self._prompt_resolver.charger(
                    template_name, id_cascade=state.run_id
                )
                # Vérifier que c'est un vrai override (pas identique au défaut)
                try:
                    default_source = self._prompt_loader.env.loader.get_source(
                        self._prompt_loader.env, template_name
                    )[0]
                    if override_source == default_source:
                        override_source = None  # identique → pas un override
                except Exception:
                    pass
            except Exception:
                override_source = None  # pas de fichier override

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

        context = {
            "objective": state.objective,
            "previous_output": previous_output,
            "last_synthesis": last_synthesis,
            "audience": self._audience,
            "constraints": self._constraints,
            "artifacts": artifacts,
        }

        # O4 : si un override existe pour ce (run_id, template_name),
        # on le rend via Jinja2 directly (pas via prompt_loader.render
        # qui chercherait le template par nom).
        if override_source is not None:
            try:
                return self._prompt_loader.env.from_string(override_source).render(**context)
            except Exception as exc:
                logger.warning(
                    "prompt_override_render_echec template=%s exc=%s fallback_defaut",
                    template_name, exc,
                )

        return self._prompt_loader.render(template_name, **context)

    def _make_call_record(
        self, iteration: int, response: Any, role: str, tier: str
    ) -> LLMCallRecord:
        """Crée un LLMCallRecord depuis une réponse provider."""
        return LLMCallRecord(
            provider=getattr(response, "provider", "unknown"),
            model=getattr(response, "model", "unknown"),
            iteration=iteration,
            role=role,
            input_tokens=getattr(response, "input_tokens", 0),
            output_tokens=getattr(response, "output_tokens", 0),
            cache_read_tokens=getattr(response, "cache_read_tokens", 0),
            cost_usd=getattr(response, "cost_usd", 0.0),
            latency_ms=getattr(response, "latency_ms", 0),
            timestamp_utc=datetime.now(UTC).isoformat(),
        )

    def _parse_verdict(self, raw_output: str) -> Verdict:
        """Permissive verdict parser — extrait le verdict de n'importe où.

        Couvre :
        - Bloc ```json ... ``` entouré de texte (test_cascade_graph).
        - Objet JSON brut noyé dans du texte (test_cascade_graph).
        - Aucun JSON → STOP par défaut avec "non parsable".

        Pour la validation stricte (rejet du texte après verdict,
        rejet des wrappers mal structurés), voir `_parse_verdict_strict`.
        """
        from ..schemas.models import Verdict as VerdictModel

        stripped = raw_output.rstrip()
        if not stripped:
            return VerdictModel(
                decision="STOP",
                justification="Verdict non parsable, STOP par défaut",
            )

        # 1. Bloc ```json ... ``` (peut être entouré de texte)
        match = re.search(r"```json\s*\n?(.*?)\n?```", stripped, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return VerdictModel.model_validate(data)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # 2. Dernier objet JSON brut dans le texte
        start = stripped.rfind("{")
        end = stripped.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(stripped[start : end + 1])
                return VerdictModel.model_validate(data)
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # 3. Aucun JSON trouvé : STOP par défaut
        return VerdictModel(
            decision="STOP",
            justification="Verdict non parsable, STOP par défaut",
        )

    def _parse_verdict_strict(self, raw_output: str) -> Verdict:
        """Verdict parser strict — applique les règles du cahier F4.

        Rejette :
        - Verdict JSON valide mais suivi de texte hors fence (signe
          d'un verdict dégénéré qui ne se termine pas proprement).
        - Verdict enveloppé dans un wrapper `{"wrapper": {...}}`
          (l'arbitre doit produire le verdict au top-level).
        - Tout format non conforme au schéma Verdict.

        Lève ValueError ; le caller (_node_verdict) appliquera la
        règle "doute profite au STOP" et retournera un verdict STOP
        avec "non parsable" dans la justification.
        """
        from ..schemas.models import Verdict as VerdictModel

        stripped = raw_output.rstrip()
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

            return VerdictModel.model_validate(data)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(
                ("Verdict JSON", "Bloc JSON", "Objet JSON", "Texte")
            ):
                raise
            try:
                details = str(exc)
            except Exception:
                details = type(exc).__name__
            raise ValueError(f"Verdict JSON invalide ou absent : {details}") from exc

