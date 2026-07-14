"""Tests unitaires pour MultiCascadeExecutor — erreurs de module et d'intégration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from goal_cascade.multicascade.module_graph import ModuleGraph
from goal_cascade.multicascade.multi_executor import (
    IntegrationFailedError,
    ModuleFailedError,
    MultiCascadeExecutor,
)
from goal_cascade.schemas.models import CascadeState, FrozenSpec

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_frozen_spec(
    module_name: str = "modA",
    objective: str = "Objectif test",
) -> FrozenSpec:
    """Construit un FrozenSpec factice avec un invariant minimal."""
    return FrozenSpec(
        module_name=module_name,
        objective=objective,
        invariants=[{"description": "Invariant test"}],
    )


def _make_single_module_graph() -> ModuleGraph:
    """Construit un ModuleGraph avec un seul module, sans dépendances."""
    graph = ModuleGraph()
    graph.add_module("modA", _make_frozen_spec())
    return graph


def _failed_state(run_id: str = "test-run", objective: str = "Objectif test") -> CascadeState:
    """Construit un CascadeState en état d'échec."""
    return CascadeState(
        run_id=run_id,
        objective=objective,
        status="failed",
        last_error="Erreur simulée",
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestRunAllFailure:
    """run_all() doit lever ModuleFailedError quand un module échoue."""

    def test_run_all_raises_on_module_failure(self) -> None:
        graph = _make_single_module_graph()

        mock_executor = MagicMock()
        mock_executor.run.return_value = _failed_state()

        mock_checker = MagicMock()

        multi = MultiCascadeExecutor(
            module_graph=graph,
            cascade_executor=mock_executor,
            interface_checker=mock_checker,
        )

        with pytest.raises(ModuleFailedError) as exc_info:
            multi.run_all(verbose=False)

        assert exc_info.value.module_id == "modA"
        assert exc_info.value.state.status == "failed"


class TestRunIntegrationFailure:
    """run_integration() doit lever IntegrationFailedError quand l'intégration échoue."""

    def test_run_integration_raises_on_failure(self) -> None:
        graph = _make_single_module_graph()

        mock_executor = MagicMock()
        mock_executor.run.return_value = _failed_state()

        mock_checker = MagicMock()

        multi = MultiCascadeExecutor(
            module_graph=graph,
            cascade_executor=mock_executor,
            interface_checker=mock_checker,
        )

        module_results = {"modA": _failed_state()}

        with pytest.raises(IntegrationFailedError) as exc_info:
            multi.run_integration(module_results=module_results, verbose=False)

        assert exc_info.value.state.status == "failed"
