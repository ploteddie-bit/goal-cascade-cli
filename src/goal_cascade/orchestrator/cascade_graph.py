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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

from ..audit_journal import redact_sensitive
from ..schemas.models import (
    CascadeState,
    IterationRole,
    LLMCallRecord,
    Verdict,
)
from .drift_detector import DriftDetector, DriftStatus
from .budget_tracker import BudgetExceeded, BudgetTracker

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
    """

    def __init__(
        self,
        provider: Any,
        synthesizer_provider: Any,
        synthesizer: Any,
        budget_tracker: BudgetTracker | None = None,
        drift_detector: DriftDetector | None = None,
        prompt_loader: Any = None,
    ):
        self.provider = provider
        self.synthesizer_provider = synthesizer_provider
        self.synthesizer = synthesizer
        self._budget = budget_tracker
        self._drift = drift_detector
        self._prompt_loader = prompt_loader

    def _build_graph(self) -> Any:
        """Construit et compile le graphe d'états G.O.A.L."""
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
        """Compile le graphe avec checkpointing SQLite."""
        graph = self._build_graph()
        import sqlite3

        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        checkpointer = SqliteSaver(conn)
        return graph.compile(checkpointer=checkpointer), checkpointer

    # ── Nœuds ──────────────────────────────────────────────────

    def _node_producer(self, state: dict) -> dict:
        """Itération 1 : Producteur (petit modèle)."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state
        iteration = 1
        prompt = self._build_prompt(cascade, IterationRole.PRODUCER)
        response = self.provider.call(prompt, role="producer", tier="small")

        call_record = self._make_call_record(iteration, response, "producer", "small")
        return {
            "current_iteration": iteration,
            "history": [call_record],
            "accumulated_cost": response.cost_usd,
            "last_raw_output": response.text,
        }

    def _node_synth(self, state: dict) -> dict:
        """Synthèse orientée objectif + détection de dérive."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state
        raw_output = state.get("last_raw_output", "")

        try:
            result = self.synthesizer.process(
                raw_output=raw_output,
                objective=cascade.objective,
                iteration_from=cascade.current_iteration,
                iteration_to=cascade.current_iteration + 1,
                previous_synthesis=cascade.last_synthesis,
                previous_artifacts=cascade.artifacts,
            )
        except Exception as exc:
            logger.error(
                "synth_failed iteration=%d error=%s",
                cascade.current_iteration,
                redact_sensitive(str(exc)),
            )
            return {"last_synthesis": None, "artifacts": cascade.artifacts}

        updates: dict[str, Any] = {
            "artifacts": result.artifacts,
            "last_synthesis": result.synthesis,
            "coverage_score": result.coverage_score,
        }

        # Détection de dérive
        if result.drift_status == DriftStatus.CRITICAL:
            logger.warning(
                "drift_critical similarity=%.4f iteration=%d",
                result.similarity_score or 0.0, cascade.current_iteration,
            )
            updates["status"] = "forced_stop"
            updates["final_verdict"] = Verdict(
                decision="STOP",
                justification=f"Dérive détectée (sim={result.similarity_score:.3f})",
            )
        elif result.drift_status == DriftStatus.WARNING:
            logger.info(
                "drift_warning similarity=%.4f iteration=%d",
                result.similarity_score or 0.0, cascade.current_iteration,
            )

        return updates

    def _node_critic(self, state: dict) -> dict:
        """Itération 2 (ou 5 si CONTINUE) : Critique (modèle moyen)."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state
        iteration = cascade.current_iteration + 1
        prompt = self._build_prompt(cascade, IterationRole.CRITIC)
        response = self.provider.call(prompt, role="critic", tier="medium")

        call_record = self._make_call_record(iteration, response, "critic", "medium")
        history = list(cascade.history) + [call_record]
        return {
            "current_iteration": iteration,
            "history": history,
            "accumulated_cost": cascade.accumulated_cost + response.cost_usd,
            "last_raw_output": response.text,
        }

    def _node_adversary(self, state: dict) -> dict:
        """Itération 3 : Adversaire (grand modèle)."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state
        iteration = cascade.current_iteration + 1
        prompt = self._build_prompt(cascade, IterationRole.ADVERSARY)
        response = self.provider.call(prompt, role="adversary", tier="large")

        call_record = self._make_call_record(iteration, response, "adversary", "large")
        history = list(cascade.history) + [call_record]
        return {
            "current_iteration": iteration,
            "history": history,
            "accumulated_cost": cascade.accumulated_cost + response.cost_usd,
            "last_raw_output": response.text,
        }

    def _node_arbiter(self, state: dict) -> dict:
        """Itération 4 : Arbitre (très grand modèle)."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state
        iteration = cascade.current_iteration + 1
        prompt = self._build_prompt(cascade, IterationRole.ARBITER)
        response = self.provider.call(prompt, role="arbiter", tier="xlarge")

        call_record = self._make_call_record(iteration, response, "arbiter", "xlarge")
        history = list(cascade.history) + [call_record]
        return {
            "current_iteration": iteration,
            "history": history,
            "accumulated_cost": cascade.accumulated_cost + response.cost_usd,
            "last_raw_output": response.text,
        }

    def _node_verdict(self, state: dict) -> dict:
        """Parse le verdict de l'arbitre."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state
        raw_output = state.get("last_raw_output", "")

        verdict = self._parse_verdict(raw_output)
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

    def _route_after_synth(self, state: dict) -> str:
        """Route après synthèse : vérifie budget + dérive + itération."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state

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
                # Le status est mis à jour par le caller (pas ici, on retourne juste le routing)
                return "forced_stop"

        # Router vers le prochain rôle selon l'itération courante
        current = cascade.current_iteration
        if current == 1:
            return "critic"
        elif current == 2:
            return "adversary"
        elif current == 3:
            return "arbiter"
        else:
            # Itération 5 (après CONTINUE) ou erreur
            return "forced_stop"

    def _route_after_verdict(self, state: dict) -> str:
        """Route après verdict : STOP ou CONTINUE (max 5)."""
        cascade = CascadeState(**state) if isinstance(state.get("run_id"), str) else state

        if cascade.status in ("forced_stop", "budget_exceeded"):
            return "forced_stop"

        if cascade.final_verdict and cascade.final_verdict.decision == "STOP":
            return "stop"

        # CONTINUE — reboucler vers critic si < max_iterations
        if cascade.current_iteration < cascade.max_iterations:
            logger.info(
                "continue_loop iteration=%d max=%d",
                cascade.current_iteration, cascade.max_iterations,
            )
            return "continue"

        # Limite atteinte
        return "forced_stop"

    # ── Helpers ────────────────────────────────────────────────

    def _build_prompt(self, state: CascadeState, role: IterationRole) -> str:
        """Construit le prompt pour un rôle donné."""
        if self._prompt_loader is not None:
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

            return self._prompt_loader.render(
                template_name,
                objective=state.objective,
                previous_output=previous_output,
                last_synthesis=last_synthesis,
                artifacts=artifacts,
            )

        # Fallback si pas de prompt_loader
        return f"Role: {role.value}\nObjective: {state.objective}\nIteration: {state.current_iteration}"

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
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )

    def _parse_verdict(self, raw_output: str) -> Verdict:
        """Extrait le verdict JSON de la sortie de l'arbitre.

        Doute profite au STOP : si le parsing échoue, retourne STOP.
        """
        # Chercher le bloc ```json ... ```
        match = re.search(r"```json\s*\n?(.*?)\n?```", raw_output, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                return Verdict(
                    decision=data.get("decision", "STOP"),
                    justification=data.get("justification", ""),
                )
            except json.JSONDecodeError:
                pass

        # Fallback : chercher un objet JSON brut
        start = raw_output.rfind("{")
        end = raw_output.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(raw_output[start:end + 1])
                return Verdict(
                    decision=data.get("decision", "STOP"),
                    justification=data.get("justification", ""),
                )
            except json.JSONDecodeError:
                pass

        # Default : STOP par défaut (doute profite au STOP)
        logger.warning("verdict_parse_failed defaulting_to_STOP")
        return Verdict(
            decision="STOP",
            justification="Verdict non parsable, STOP par défaut",
        )


# ── Wrappers rétrocompatibles ──────────────────────────────────
# cascade_executor.py utilise encore ces fonctions (architecture
# à nœud unique "iteration"). Elles sont préservées temporairement
# en attendant la migration complète vers CascadeGraph.


def build_cascade_graph(iteration_fn) -> StateGraph:
    """Construit un graphe LangGraph simple avec un nœud 'iteration'.

    Wrapper rétrocompatible pour cascade_executor._run_with_graph().
    Préférer CascadeGraph pour les nouvelles implémentations.
    """

    def should_continue(state: dict) -> str:
        status = state.get("status", "running")
        if status != "running":
            return "end"
        current = state.get("current_iteration", 0)
        cascade = state.get("cascade", {})
        max_iter = cascade.get("max_iterations", 5)
        if current >= max_iter:
            return "end"
        return "continue"

    graph = StateGraph(dict)
    graph.add_node("iteration", iteration_fn)
    graph.add_conditional_edges(
        "iteration",
        should_continue,
        {"continue": "iteration", "end": END},
    )
    graph.set_entry_point("iteration")
    return graph


def compile_with_sqlite(graph: StateGraph, db_path: Path | str):
    """Compile le graphe avec un checkpointer SQLite.

    Wrapper rétrocompatible pour cascade_executor._run_with_graph().
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = graph.compile(checkpointer=checkpointer)
    return compiled, checkpointer
