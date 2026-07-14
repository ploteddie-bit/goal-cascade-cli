"""Tests de sécurité C1-C6 pour MultiCascadeExecutor.

C1 : validation acyclique avant exécution.
C2 : vérification budgétaire avant chaque module / intégration.
C3 : arrêt propre sur échec module avec checkpoint.
C4 : cascade d'intégration bornée à 5 itérations.
C5 : pas de parallélisme non contrôlé.
C6 : contrats d'interface vérifiés après chaque batch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from goal_cascade.multicascade.interface_checker import CheckResult
from goal_cascade.multicascade.module_graph import ModuleGraph
from goal_cascade.multicascade.multi_executor import (
    InterfaceViolationError,
    ModuleFailedError,
    MultiCascadeExecutor,
)
from goal_cascade.orchestrator.budget_tracker import BudgetConfig, BudgetExceeded, BudgetTracker
from goal_cascade.schemas.models import (
    CascadeState,
    FrozenSpec,
    InterfaceContract,
    Verdict,
)

# ── Helpers ─────────────────────────────────────────────────────────


def _make_spec(module_name: str = "mod", objective: str = "test") -> FrozenSpec:
    return FrozenSpec(
        module_name=module_name,
        objective=objective,
        invariants=[{"description": "inv"}],
    )


def _make_state(
    module_id: str = "mod",
    status: str = "stopped",
    cost: float = 0.0,
    decision: str = "STOP",
) -> CascadeState:
    return CascadeState(
        run_id=f"{module_id}-run",
        objective="test",
        status=status,
        accumulated_cost=cost,
        final_verdict=Verdict(
            decision=decision,
            justification="test",
        ),
    )


def _make_cyclic_graph() -> ModuleGraph:
    """Graphe avec un cycle : A -> B -> C -> A."""
    graph = ModuleGraph()
    for mid in ("A", "B", "C"):
        graph.add_module(mid, _make_spec(module_name=mid))
    contract = InterfaceContract(
        contract_id="c",
        producer_module="A",
        consumer_module="B",
        output_description="x",
        input_description="x",
    )
    graph.add_dependency("A", "B", contract)
    graph.add_dependency("B", "C", contract)
    graph.add_dependency("C", "A", contract)
    return graph


def _make_two_module_graph() -> ModuleGraph:
    """Graphe A -> B."""
    graph = ModuleGraph()
    graph.add_module("A", _make_spec(module_name="A"))
    graph.add_module("B", _make_spec(module_name="B"))
    contract = InterfaceContract(
        contract_id="A->B",
        producer_module="A",
        consumer_module="B",
        output_description="x",
        input_description="x",
    )
    graph.add_dependency("A", "B", contract)
    return graph


# ── C1 : validation acyclique ──────────────────────────────────────


def test_run_all_validates_acyclicity_before_running_modules() -> None:
    """Un graphe cyclique doit échouer AVANT que quiconque ne s'exécute."""
    graph = _make_cyclic_graph()
    mock_executor = MagicMock()
    mock_checker = MagicMock()

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
    )

    with pytest.raises(nx.HasACycle):
        multi.run_all(verbose=False)

    mock_executor.run.assert_not_called()


# ── C2 : budget check par module ───────────────────────────────────


def _budget_tracker_with_low_limit(tmp_path: Path) -> BudgetTracker:
    config = BudgetConfig(
        max_per_run_usd=0.01,
        max_per_day_usd=100.0,
        hard_stop=True,
    )
    return BudgetTracker(
        config=config,
        daily_total_path=tmp_path / "budget.json",
    )


def test_budget_checked_before_each_module(tmp_path: Path) -> None:
    """Le budget global est vérifié avant chaque module."""
    graph = ModuleGraph()
    graph.add_module("A", _make_spec(module_name="A"))
    graph.add_module("B", _make_spec(module_name="B"))

    call_order: list[str] = []

    def fake_run(state: CascadeState, **kwargs: Any) -> CascadeState:
        call_order.append(state.run_id)
        # Premier module coûte 0.02, ce qui dépasse le budget global pour le suivant.
        cost = 0.02 if "A" in state.run_id else 0.0
        return _make_state(module_id=state.run_id.split("-")[0], cost=cost)

    mock_executor = MagicMock()
    mock_executor.run.side_effect = fake_run
    mock_checker = MagicMock()
    budget_tracker = _budget_tracker_with_low_limit(tmp_path)

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
        budget_tracker=budget_tracker,
    )

    with pytest.raises(BudgetExceeded):
        multi.run_all(verbose=False)

    assert any(c.startswith("A-") for c in call_order)
    assert not any(c.startswith("B-") for c in call_order)  # B n'a jamais démarré


def test_budget_checked_before_integration(tmp_path: Path) -> None:
    """Le budget global est vérifié avant la cascade d'intégration."""
    graph = ModuleGraph()
    graph.add_module("A", _make_spec(module_name="A"))

    mock_executor = MagicMock()
    mock_executor.run.return_value = _make_state(cost=0.02)
    mock_checker = MagicMock()
    budget_tracker = _budget_tracker_with_low_limit(tmp_path)

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
        budget_tracker=budget_tracker,
    )
    # Simuler un coût déjà accumulé par les modules avant l'intégration.
    multi._total_cost = 0.02

    with pytest.raises(BudgetExceeded):
        multi.run_integration(
            module_results={"A": _make_state(cost=0.02)},
            verbose=False,
        )


# ── C3 : arrêt propre sur échec module ─────────────────────────────


def test_failed_module_saves_checkpoint_before_raising() -> None:
    """Un module échoué déclenche une sauvegarde d'état avant l'exception."""
    graph = ModuleGraph()
    graph.add_module("A", _make_spec(module_name="A"))

    failed_state = _make_state(status="failed", decision="STOP")
    mock_executor = MagicMock()
    mock_executor.run.return_value = failed_state
    mock_checker = MagicMock()

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
    )

    with (
        patch("goal_cascade.multicascade.multi_executor.state_manager.save_state") as mock_save,
        pytest.raises(ModuleFailedError) as exc_info,
    ):
        multi.run_all(verbose=False)

    mock_save.assert_called_once()
    assert exc_info.value.state is failed_state


# ── C4 : intégration bornée ────────────────────────────────────────


def test_integration_max_iterations_is_five() -> None:
    """La cascade d'intégration est limitée à 5 itérations."""
    graph = ModuleGraph()
    graph.add_module("A", _make_spec(module_name="A"))

    mock_executor = MagicMock()
    mock_executor.run.return_value = _make_state()
    mock_checker = MagicMock()

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
    )

    multi.run_integration(module_results={"A": _make_state()}, verbose=False)

    assert mock_executor.run.called
    passed_state = mock_executor.run.call_args.kwargs["state"]
    assert passed_state.max_iterations == 5


# ── C5 : pas de parallélisme non contrôlé ──────────────────────────


def test_no_uncontrolled_parallelism_imports() -> None:
    """L'exécuteur ne doit pas utiliser asyncio, threading ou concurrent.futures."""
    import goal_cascade.multicascade.multi_executor as multi_module

    # Vérification statique du fichier source.
    source = Path(multi_module.__file__).read_text(encoding="utf-8")
    assert "import asyncio" not in source
    assert "import threading" not in source
    assert "import concurrent.futures" not in source
    assert "asyncio.gather" not in source
    assert "Thread(" not in source
    assert "ProcessPoolExecutor" not in source
    assert "ThreadPoolExecutor" not in source


# ── C6 : vérification des interfaces après chaque batch ────────────


def test_interface_check_called_after_batch_with_correct_signature() -> None:
    """InterfaceChecker.check est appelé après le batch avec le bon API."""
    graph = _make_two_module_graph()

    def fake_run(state: CascadeState, **kwargs: Any) -> CascadeState:
        return _make_state(module_id=state.run_id.split("-")[0])

    mock_executor = MagicMock()
    mock_executor.run.side_effect = fake_run
    mock_checker = MagicMock()
    mock_checker.check.return_value = CheckResult(passed=True)

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
    )

    multi.run_all(verbose=False)

    # A est producteur du contrat A->B, B est consommateur.
    # Les deux sont vérifiés après leur batch respectif.
    assert mock_checker.check.call_count == 2

    checked_modules = {
        call.kwargs["current_module_id"] for call in mock_checker.check.call_args_list
    }
    assert checked_modules == {"A", "B"}

    b_call = next(
        call
        for call in mock_checker.check.call_args_list
        if call.kwargs["current_module_id"] == "B"
    )
    assert any(c.contract_id == "A->B" for c in b_call.kwargs["contracts"])


def test_interface_violation_raises_after_batch() -> None:
    """Une interface invalide détectée après batch lève InterfaceViolationError."""
    graph = _make_two_module_graph()

    def fake_run(state: CascadeState, **kwargs: Any) -> CascadeState:
        return _make_state(module_id=state.run_id.split("-")[0])

    def fake_check(contracts, module_states, current_module_id: str) -> CheckResult:
        # Faire échouer uniquement la vérification du consommateur B.
        if current_module_id == "B":
            return CheckResult(passed=False, failures=[])
        return CheckResult(passed=True)

    mock_executor = MagicMock()
    mock_executor.run.side_effect = fake_run
    mock_checker = MagicMock()
    mock_checker.check.side_effect = fake_check

    multi = MultiCascadeExecutor(
        module_graph=graph,
        cascade_executor=mock_executor,
        interface_checker=mock_checker,
    )

    with pytest.raises(InterfaceViolationError) as exc_info:
        multi.run_all(verbose=False)

    assert exc_info.value.module_id == "B"
