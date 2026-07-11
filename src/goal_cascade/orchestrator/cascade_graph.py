"""Graphe LangGraph pour une cascade G.O.A.L. unique.

Remplace la boucle while de _run_loop par un StateGraph LangGraph
pour bénéficier du checkpointing SQLite natif et de goal resume.

Architecture :
    START → iteration → (should_continue?) → iteration → ... → END

Le nœud "iteration" encapsule une itération complète : garde budget +
max_iterations + provider call + synthèse + drift + verdict. La condition
"should_continue" vérifie le statut et le compteur d'itérations.

Checkpointing :
    SqliteSaver stocke l'état à chaque transition de nœud.
    goal resume invoque le même graph avec le même thread_id pour reprendre.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.sqlite import SqliteSaver

try:
    import structlog

    _logger: Any = structlog.get_logger(__name__)
except ImportError:
    _logger = logging.getLogger(__name__)


# ── État du graphe ──────────────────────────────────────────────

class GraphState(TypedDict):
    """État du graphe LangGraph pour une cascade G.O.A.L.

    Le champ 'cascade' contient le CascadeState sérialisé (dict Pydantic).
    Les champs 'run_id', 'current_iteration' et 'status' sont des
    métadonnées de contrôle pour le checkpointing et la condition de
    continuation.
    """

    # CascadeState sérialisé via model_dump()
    cascade: dict[str, Any]
    # Identifiant du run
    run_id: str
    # Numéro de l'itération en cours
    current_iteration: int
    # Statut de la cascade
    status: str


# ── Condition de continuation ───────────────────────────────────

def should_continue(state: GraphState) -> str:
    """Détermine si la cascade doit continuer ou s'arrêter.

    Returns:
        "continue" si la cascade doit continuer, "end" sinon.
    """
    status = state.get("status", "running")
    if status != "running":
        return "end"

    current = state.get("current_iteration", 0)
    cascade = state.get("cascade", {})
    max_iter = cascade.get("max_iterations", 5)
    if current >= max_iter:
        return "end"

    return "continue"


# ── Construction du graphe ──────────────────────────────────────

def build_cascade_graph(iteration_fn) -> StateGraph:
    """Construit le graphe LangGraph pour une cascade G.O.A.L.

    Args:
        iteration_fn: Callable(GraphState) -> dict
            Fonction d'itération injectée par CascadeExecutor.
            Prend l'état du graphe, exécute une itération, retourne
            un dict partiel (current_iteration, status, cascade).

    Returns:
        StateGraph non compilé. L'appelant compile avec checkpointer.
    """
    graph = StateGraph(GraphState)

    graph.add_node("iteration", iteration_fn)

    graph.add_conditional_edges(
        "iteration",
        should_continue,
        {
            "continue": "iteration",
            "end": END,
        },
    )
    graph.set_entry_point("iteration")

    return graph


def compile_with_sqlite(graph: StateGraph, db_path: Path | str):
    """Compile le graphe avec un checkpointer SQLite.

    Args:
        graph: StateGraph non compilé.
        db_path: Chemin vers le fichier SQLite de checkpointing.

    Returns:
        Tuple (compiled_graph, checkpointer).
        Le checkpointer est un SqliteSaver prêt à l'emploi.
    """
    import sqlite3

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    compiled = graph.compile(checkpointer=checkpointer)
    return compiled, checkpointer
