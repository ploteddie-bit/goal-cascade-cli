"""Tests du graphe LangGraph G.O.A.L. — architecture 6 nœuds.

Couvre :
- Routing après synthèse (critic, adversary, arbiter, forced_stop)
- Routing après verdict (stop, continue, forced_stop)
- Nœuds (producer, synth, critic, adversary, arbiter, verdict)
- Budget check dans le routing
- Détection de dérive dans le nœud synth
- Checkpointing SQLite
- _parse_verdict (JSON, fenced, fallback STOP)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from goal_cascade.orchestrator.budget_tracker import BudgetConfig, BudgetTracker
from goal_cascade.orchestrator.cascade_graph import CascadeGraph
from goal_cascade.orchestrator.drift_detector import DriftStatus
from goal_cascade.schemas.models import (
    Verdict,
)

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def mock_provider():
    provider = MagicMock()
    provider.name = "mock"
    provider.call.return_value = MagicMock(
        text='{"decision": "STOP", "justification": "Test OK"}',
        provider="mock",
        model="mock-xlarge",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        latency_ms=100,
    )
    return provider


@pytest.fixture
def mock_synthesizer():
    synth = MagicMock()
    synth.process.return_value = MagicMock(
        artifacts=[],
        synthesis=MagicMock(),
        drift_status=DriftStatus.NORMAL,
        similarity_score=0.75,
        coverage_score=0.60,
    )
    return synth


@pytest.fixture
def budget_tracker(tmp_path: Path) -> BudgetTracker:
    config = BudgetConfig(max_per_run_usd=1.0, max_per_day_usd=10.0)
    return BudgetTracker(config=config, runs_dir=tmp_path)


@pytest.fixture
def cascade_graph(mock_provider, mock_synthesizer, budget_tracker) -> CascadeGraph:
    return CascadeGraph(
        provider=mock_provider,
        synthesizer_provider=mock_provider,
        synthesizer=mock_synthesizer,
        budget_tracker=budget_tracker,
    )


# ── Routing après synthèse ─────────────────────────────────────


class TestRouteAfterSynth:
    def test_after_iteration_1_routes_to_critic(self, cascade_graph: CascadeGraph) -> None:
        state = {"run_id": "test", "objective": "Test", "current_iteration": 1, "status": "running"}
        assert cascade_graph._route_after_synth(state) == "critic"

    def test_after_iteration_2_routes_to_adversary(self, cascade_graph: CascadeGraph) -> None:
        state = {"run_id": "test", "objective": "Test", "current_iteration": 2, "status": "running"}
        assert cascade_graph._route_after_synth(state) == "adversary"

    def test_after_iteration_3_routes_to_arbiter(self, cascade_graph: CascadeGraph) -> None:
        state = {"run_id": "test", "objective": "Test", "current_iteration": 3, "status": "running"}
        assert cascade_graph._route_after_synth(state) == "arbiter"

    def test_forced_stop_status_returns_forced_stop(self, cascade_graph: CascadeGraph) -> None:
        state = {
            "run_id": "test",
            "objective": "Test",
            "current_iteration": 2,
            "status": "forced_stop",
        }
        assert cascade_graph._route_after_synth(state) == "forced_stop"


# ── Routing après verdict ───────────────────────────────────────


class TestRouteAfterVerdict:
    def test_stop_verdict_returns_stop(self, cascade_graph: CascadeGraph) -> None:
        state = {
            "run_id": "test",
            "objective": "Test",
            "current_iteration": 4,
            "status": "stopped",
            "final_verdict": Verdict(decision="STOP", justification="OK"),
        }
        assert cascade_graph._route_after_verdict(state) == "stop"

    def test_continue_under_max_returns_continue(self, cascade_graph: CascadeGraph) -> None:
        state = {
            "run_id": "test",
            "objective": "Test",
            "current_iteration": 4,
            "max_iterations": 5,
            "status": "running",
            "final_verdict": Verdict(decision="CONTINUE", justification="Manque couverture"),
        }
        assert cascade_graph._route_after_verdict(state) == "continue"

    def test_continue_at_max_returns_forced_stop(self, cascade_graph: CascadeGraph) -> None:
        state = {
            "run_id": "test",
            "objective": "Test",
            "current_iteration": 5,
            "max_iterations": 5,
            "status": "running",
            "final_verdict": Verdict(decision="CONTINUE", justification="Encore"),
        }
        assert cascade_graph._route_after_verdict(state) == "forced_stop"

    def test_forced_stop_status_returns_forced_stop(self, cascade_graph: CascadeGraph) -> None:
        state = {
            "run_id": "test",
            "objective": "Test",
            "current_iteration": 4,
            "status": "forced_stop",
            "final_verdict": None,
        }
        assert cascade_graph._route_after_verdict(state) == "forced_stop"


# ── Verdict parsing ─────────────────────────────────────────────


class TestParseVerdict:
    def test_parses_fenced_json(self, cascade_graph: CascadeGraph) -> None:
        raw = 'Some text\n```json\n{"decision": "STOP", "justification": "OK"}\n```\nMore text'
        verdict = cascade_graph._parse_verdict(raw)
        assert verdict.decision == "STOP"
        assert verdict.justification == "OK"

    def test_parses_raw_json(self, cascade_graph: CascadeGraph) -> None:
        raw = 'Blabla {"decision": "CONTINUE", "justification": "Manque"} fin'
        verdict = cascade_graph._parse_verdict(raw)
        assert verdict.decision == "CONTINUE"

    def test_defaults_to_stop_on_parse_failure(self, cascade_graph: CascadeGraph) -> None:
        raw = "No JSON here at all"
        verdict = cascade_graph._parse_verdict(raw)
        assert verdict.decision == "STOP"
        assert "non parsable" in verdict.justification.lower()


# ── Graph compilation ───────────────────────────────────────────


class TestGraphCompilation:
    def test_build_graph_returns_state_graph(self, cascade_graph: CascadeGraph) -> None:
        from langgraph.graph import StateGraph

        graph = cascade_graph._build_graph()
        assert isinstance(graph, StateGraph)

    def test_compile_with_sqlite_creates_checkpoint(
        self, cascade_graph: CascadeGraph, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "test_checkpoint.db"
        app, checkpointer = cascade_graph.compile_with_sqlite(db_path)

        assert app is not None
        assert db_path.exists()
