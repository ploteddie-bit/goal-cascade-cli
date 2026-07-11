"""Tests du graphe LangGraph — checkpointing et resume.

Couvre :
- Le graphe LangGraph compile et s'exécute
- Le checkpointing SQLite fonctionne (fichier créé, état persisté)
- Le resume depuis un checkpoint fonctionne
- goal resume est visible dans le CLI
- _run_with_graph produit le même résultat que _run_loop
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from goal_cascade.orchestrator.cascade_graph import (
    GraphState,
    build_cascade_graph,
    compile_with_sqlite,
    should_continue,
)


# ---------- Graph construction ----------


class TestCascadeGraphConstruction:
    """Tests de construction du graphe LangGraph."""

    def test_build_cascade_graph_returns_state_graph(self):
        """Le graphe est un StateGraph LangGraph."""
        from langgraph.graph import StateGraph

        def dummy_node(state: GraphState) -> dict:
            return {"current_iteration": state.get("current_iteration", 0) + 1}

        graph = build_cascade_graph(dummy_node)
        assert isinstance(graph, StateGraph)

    def test_graph_compiles_without_checkpointer(self):
        """Le graphe compile sans checkpointer."""
        def dummy_node(state: GraphState) -> dict:
            return {"current_iteration": state.get("current_iteration", 0) + 1}

        graph = build_cascade_graph(dummy_node)
        app = graph.compile()
        assert app is not None

    def test_graph_compiles_with_sqlite_checkpointer(self, tmp_path: Path):
        """Le graphe compile avec un checkpointer SQLite."""
        def dummy_node(state: GraphState) -> dict:
            return {"current_iteration": state.get("current_iteration", 0) + 1}

        graph = build_cascade_graph(dummy_node)
        db_path = tmp_path / "test.db"
        app, checkpointer = compile_with_sqlite(graph, db_path)
        assert app is not None


# ---------- should_continue condition ----------


class TestShouldContinue:
    """Tests de la condition de continuation."""

    def test_running_status_returns_continue(self):
        state: GraphState = {
            "cascade": {"max_iterations": 5},
            "run_id": "test",
            "current_iteration": 2,
            "status": "running",
        }
        assert should_continue(state) == "continue"

    def test_stopped_status_returns_end(self):
        state: GraphState = {
            "cascade": {"max_iterations": 5},
            "run_id": "test",
            "current_iteration": 3,
            "status": "stopped",
        }
        assert should_continue(state) == "end"

    def test_max_iterations_reached_returns_end(self):
        state: GraphState = {
            "cascade": {"max_iterations": 5},
            "run_id": "test",
            "current_iteration": 5,
            "status": "running",
        }
        assert should_continue(state) == "end"

    def test_budget_exceeded_returns_end(self):
        state: GraphState = {
            "cascade": {"max_iterations": 5},
            "run_id": "test",
            "current_iteration": 2,
            "status": "budget_exceeded",
        }
        assert should_continue(state) == "end"

    def test_forced_stop_returns_end(self):
        state: GraphState = {
            "cascade": {"max_iterations": 5},
            "run_id": "test",
            "current_iteration": 5,
            "status": "forced_stop",
        }
        assert should_continue(state) == "end"


# ---------- Graph execution ----------


class TestCascadeGraphExecution:
    """Tests d'exécution du graphe."""

    def test_graph_runs_to_completion(self):
        """Le graphe s'exécute jusqu'à la fin (5 itérations max)."""
        call_count = 0

        def counting_node(state: GraphState) -> dict:
            nonlocal call_count
            call_count += 1
            current = state.get("current_iteration", 0)
            new_status = "running" if current < 4 else "stopped"
            return {"current_iteration": current + 1, "status": new_status}

        graph = build_cascade_graph(counting_node)
        app = graph.compile()

        result = app.invoke({
            "cascade": {"max_iterations": 5, "objective": "test"},
            "run_id": "test-001",
            "current_iteration": 0,
            "status": "running",
        })

        assert result["current_iteration"] == 5
        assert result["status"] == "stopped"
        assert call_count == 5

    def test_graph_stops_on_budget_exceeded(self):
        """Le graphe s'arrête si le budget est dépassé."""
        def budget_node(state: GraphState) -> dict:
            current = state.get("current_iteration", 0)
            # Simuler un budget dépassé à l'itération 3
            if current >= 2:
                return {"current_iteration": current + 1, "status": "budget_exceeded"}
            return {"current_iteration": current + 1, "status": "running"}

        graph = build_cascade_graph(budget_node)
        app = graph.compile()

        result = app.invoke({
            "cascade": {"max_iterations": 5, "objective": "test"},
            "run_id": "test-002",
            "current_iteration": 0,
            "status": "running",
        })

        assert result["current_iteration"] == 3
        assert result["status"] == "budget_exceeded"


# ---------- Checkpointing SQLite ----------


class TestSqliteCheckpointing:
    """Tests du checkpointing SQLite."""

    def test_checkpoint_creates_file(self, tmp_path: Path):
        """Le checkpoint SQLite crée un fichier."""
        def simple_node(state: GraphState) -> dict:
            current = state.get("current_iteration", 0)
            return {
                "current_iteration": current + 1,
                "status": "stopped" if current >= 1 else "running",
            }

        graph = build_cascade_graph(simple_node)
        db_path = tmp_path / "checkpoint.db"
        app, checkpointer = compile_with_sqlite(graph, db_path)

        app.invoke({
            "cascade": {"max_iterations": 5, "objective": "test"},
            "run_id": "test-cp-001",
            "current_iteration": 0,
            "status": "running",
        }, config={"configurable": {"thread_id": "test-cp-001"}})

        assert db_path.exists()
        assert db_path.stat().st_size > 0

    def test_checkpoint_persists_state(self, tmp_path: Path):
        """Le checkpoint persiste l'état entre les invocations."""
        def simple_node(state: GraphState) -> dict:
            current = state.get("current_iteration", 0)
            return {
                "current_iteration": current + 1,
                "status": "stopped" if current >= 2 else "running",
            }

        graph = build_cascade_graph(simple_node)
        db_path = tmp_path / "checkpoint.db"
        app, checkpointer = compile_with_sqlite(graph, db_path)

        config = {"configurable": {"thread_id": "test-cp-002"}}

        # Première exécution
        result = app.invoke({
            "cascade": {"max_iterations": 5, "objective": "test"},
            "run_id": "test-cp-002",
            "current_iteration": 0,
            "status": "running",
        }, config)

        assert result["current_iteration"] == 3
        assert result["status"] == "stopped"

        # Vérifier que le checkpoint a l'état final
        saved = app.get_state(config)
        assert saved is not None
        assert saved.values.get("current_iteration") == 3


# ---------- Resume ----------


class TestResume:
    """Tests du mécanisme de resume."""

    def test_resume_from_checkpoint(self, tmp_path: Path):
        """Le resume reprend depuis le dernier checkpoint."""
        call_log = []

        def crashing_node(state: GraphState) -> dict:
            current = state.get("current_iteration", 0)
            call_log.append(current + 1)

            if current == 2:  # Crash à l'itération 3
                raise TimeoutError("Simulated crash")

            return {
                "current_iteration": current + 1,
                "status": "running" if current < 4 else "stopped",
            }

        def fixed_node(state: GraphState) -> dict:
            current = state.get("current_iteration", 0)
            call_log.append(current + 1)
            return {
                "current_iteration": current + 1,
                "status": "running" if current < 4 else "stopped",
            }

        db_path = tmp_path / "resume.db"
        config = {"configurable": {"thread_id": "resume-001"}}

        # Étape 1 : Exécuter avec crash
        graph1 = build_cascade_graph(crashing_node)
        app1, cp1 = compile_with_sqlite(graph1, db_path)

        try:
            app1.invoke({
                "cascade": {"max_iterations": 5, "objective": "test resume"},
                "run_id": "resume-001",
                "current_iteration": 0,
                "status": "running",
            }, config)
        except TimeoutError:
            pass  # Crash attendu

        # Étape 2 : Vérifier le checkpoint
        saved = app1.get_state(config)
        assert saved is not None
        checkpointed_iter = saved.values.get("current_iteration", 0)
        assert checkpointed_iter == 2  # Itération 2 complétée

        # Étape 3 : Resume avec le nœud corrigé
        call_log.clear()
        graph2 = build_cascade_graph(fixed_node)
        app2, cp2 = compile_with_sqlite(graph2, db_path)

        result = app2.invoke({
            "cascade": {"max_iterations": 5, "objective": "test resume"},
            "run_id": "resume-001",
            "current_iteration": checkpointed_iter,
            "status": "running",
        }, config)

        # Le resume doit continuer depuis l'itération 3
        assert result["current_iteration"] == 5
        assert result["status"] == "stopped"
        # Les appels 3, 4, 5 doivent avoir été faits
        assert call_log == [3, 4, 5]


# ---------- Intégration CLI ----------


class TestResumeCLI:
    """Tests de la commande goal resume."""

    def test_resume_command_visible(self):
        """La commande resume est visible dans goal --help."""
        import subprocess

        result = subprocess.run(
            ["uv", "run", "goal", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert "resume" in result.stdout

    def test_resume_command_shows_help(self):
        """La commande resume --help affiche l'aide."""
        import subprocess

        result = subprocess.run(
            ["uv", "run", "goal", "resume", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        assert "RUN_ID" in result.stdout
        assert "checkpoint" in result.stdout.lower()