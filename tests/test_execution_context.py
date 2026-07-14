"""Tests pour ``orchestrator.execution_context``.

Couvre deux invariants non-négociables du refactor commit 2 :

1. **Pas de cycle d'import** : importer ``execution_context`` ne doit PAS déclencher
   le chargement de ``cli.py``. Sinon le lazy import de ``_build_provider`` ne casse
   pas réellement le cycle. Testé via subprocess pour éviter le cache de modules
   inter-tests.

2. **Factory fonctionnelle** : ``build_execution_context(config, ...)`` retourne un
   ``ExecutionContext`` valide avec un ``RoleMappedProvider``, un synthétiseur
   distinct et un ``BudgetTracker``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_import_execution_context_does_not_load_cli() -> None:
    """L'import de execution_context doit être possible SANS charger cli.py.

    Sans cette garantie, le lazy import de ``_build_provider`` à l'intérieur de
    ``build_execution_context`` ne casse pas réellement le cycle :

        cli.py → orchestrator.cascade_executor → execution_context → cli._build_provider
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import goal_cascade.orchestrator.execution_context; "
                "assert 'goal_cascade.cli' not in sys.modules, "
                "'CYCLE: execution_context a chargé cli.py'; "
                "print('OK')"
            ),
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Import cycle détecté.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "OK" in result.stdout, f"Sortie inattendue : {result.stdout!r}"


def test_build_execution_context_returns_valid_context() -> None:
    """Factory retourne un ExecutionContext avec les 3 attributs attendus."""
    from goal_cascade.config import GoalConfig, ProvidersConfig
    from goal_cascade.orchestrator.budget_tracker import BudgetTracker
    from goal_cascade.orchestrator.execution_context import (
        ExecutionContext,
        build_execution_context,
    )
    from goal_cascade.providers.router import RoleMappedProvider

    # Tous les rôles pointent vers mock : valide pour le test, le router n'enforce
    # pas la diversité (c'est la CLI qui le fait via ``diversity_failure``).
    config = GoalConfig(
        providers=ProvidersConfig(
            enabled=["mock", "mock"],
            role_mapping={
                "producer": "mock",
                "critic": "mock",
                "adversary": "mock",
                "arbiter": "mock",
            },
            synthesizer="mock",
        ),
    )

    ctx = build_execution_context(config, synthesizer_model=None)

    assert isinstance(ctx, ExecutionContext)
    assert isinstance(ctx.provider, RoleMappedProvider)
    assert ctx.synthesizer_provider is not None
    assert ctx.provider is not ctx.synthesizer_provider  # instances distinctes
    assert isinstance(ctx.budget_tracker, BudgetTracker)


def test_execution_context_is_frozen() -> None:
    """Le dataclass est frozen — un ExecutionContext construit ne peut pas muter."""
    from goal_cascade.config import GoalConfig, ProvidersConfig
    from goal_cascade.orchestrator.execution_context import build_execution_context

    config = GoalConfig(
        providers=ProvidersConfig(
            enabled=["mock"],
            role_mapping={
                "producer": "mock",
                "critic": "mock",
                "adversary": "mock",
                "arbiter": "mock",
            },
            synthesizer="mock",
        ),
    )

    ctx = build_execution_context(config)

    # Tenter de muter un attribut frozen lève FrozenInstanceError.
    import dataclasses

    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        ctx.provider = None  # type: ignore[misc]


def test_cascade_run_wires_real_provider_through_multi_executor(
    tmp_path, monkeypatch
) -> None:
    """E2E : ``cascade_run --config real.toml`` câble un ``RoleMappedProvider`` (pas Mock brut).

    Stratégie : monkeypatch ``MultiCascadeExecutor`` à la source
    (``goal_cascade.multicascade.multi_executor.MultiCascadeExecutor``) pour capturer
    le ``cascade_executor`` ET le ``budget_tracker`` passés par ``cascade_run``.
    Le patch au niveau source fonctionne car ``cascade_run`` importe la classe
    **dans la fonction** (donc l'import lit la valeur patchée à chaque invocation).

    Vérifie :
        - ``cascade_exec.provider`` est un ``RoleMappedProvider`` (pas ``MockProvider``)
        - ``provider`` et ``synthesizer_provider`` sont des instances distinctes
        - ``MultiCascadeExecutor`` reçoit un ``budget_tracker`` non-None (config chargée)

    Note architecture : le ``CascadeExecutor`` interne à ``cascade_run`` n'a PAS
    son propre ``budget_tracker`` (≠ ``run``/``resume``). Le budget est géré
    globalement au niveau ``MultiCascadeExecutor``. C'est intentionnel — le test
    vérifie donc le budget_tracker au niveau du MultiCascadeExecutor, pas du
    CascadeExecutor interne.
    """
    import json
    import textwrap

    from typer.testing import CliRunner

    from goal_cascade.cli import app
    from goal_cascade.providers.router import RoleMappedProvider

    # ── Plan.json minimal (1 module avec FrozenSpec valide) ─────────────
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(
        json.dumps(
            {
                "modules": [
                    {
                        "module_id": "modA",
                        "spec": {
                            "module_name": "modA",
                            "objective": "Test objective",
                            "invariants": [
                                {
                                    "description": "Test invariant",
                                    "category": "functional",
                                }
                            ],
                            "max_lines": 3000,
                        },
                    }
                ]
            }
        )
    )

    # ── Config TOML avec tous les rôles = mock ──────────────────────────
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        textwrap.dedent("""
            [providers]
            enabled = ["mock", "mock"]
            role_mapping = {producer = "mock", critic = "mock", adversary = "mock", arbiter = "mock"}
            synthesizer = "mock"

            [budget]
            max_per_run_usd = 1.0
            max_per_day_usd = 10.0
            warn_at_percent = 80
            hard_stop = true
        """).strip()
    )

    # ── Fake MultiCascadeExecutor : capture le cascade_executor et budget_tracker ──
    captured_executors: list = []
    captured_budget_trackers: list = []

    class _FakeState:
        accumulated_cost = 0.0
        current_iteration = 0
        final_verdict = None

    class _FakeMultiCascadeExecutor:
        def __init__(self, module_graph, cascade_executor, budget_tracker=None):
            captured_executors.append(cascade_executor)
            captured_budget_trackers.append(budget_tracker)

        def run_all(self):
            return {}

        def run_integration(self, results):
            return _FakeState()

    monkeypatch.setattr(
        "goal_cascade.multicascade.multi_executor.MultiCascadeExecutor",
        _FakeMultiCascadeExecutor,
    )

    # ── Invocation cascade_run via CliRunner ─────────────────────────────
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["cascade-run", str(plan_file), "--config", str(config_file)],
    )

    # ── Vérifications ───────────────────────────────────────────────────
    assert result.exit_code == 0, (
        f"cascade-run failed (exit {result.exit_code}):\n{result.output}"
    )
    assert len(captured_executors) == 1, (
        f"Expected exactly 1 MultiCascadeExecutor, got {len(captured_executors)}"
    )

    cascade_exec = captured_executors[0]
    budget_tracker = captured_budget_trackers[0]

    # Régression : si on hardcode MockProvider à nouveau, on aurait MockProvider ici.
    assert isinstance(cascade_exec.provider, RoleMappedProvider), (
        f"REGRESSION: cascade_exec.provider doit être un RoleMappedProvider, "
        f"reçu {type(cascade_exec.provider).__name__}"
    )
    assert cascade_exec.provider is not cascade_exec.synthesizer_provider, (
        "provider et synthesizer_provider doivent être des instances distinctes "
        "(CascadeExecutor lève ValueError sinon)"
    )
    # Budget global au niveau multi-cascade (≠ CascadeExecutor interne).
    assert budget_tracker is not None, (
        "REGRESSION: budget_tracker devrait être passé au MultiCascadeExecutor "
        "quand config chargée (vérifié au niveau multi-cascade, pas CascadeExecutor)"
    )


def test_missing_goal_roles_raises_value_error() -> None:
    """Une config sans les 4 rôles G.O.A.L. obligatoires lève ValueError."""
    from goal_cascade.config import GoalConfig, ProvidersConfig
    from goal_cascade.orchestrator.execution_context import build_execution_context

    config = GoalConfig(
        providers=ProvidersConfig(
            enabled=["mock"],
            role_mapping={
                "producer": "mock",
                "critic": "mock",
                # adversary et arbiter manquants
            },
            synthesizer="mock",
        ),
    )

    with __import__("pytest").raises(ValueError, match="Rôles G.O.A.L. manquants"):
        build_execution_context(config)


def test_missing_goal_roles_error_lists_missing() -> None:
    """Le message d'erreur liste les rôles manquants par nom."""
    from goal_cascade.config import GoalConfig, ProvidersConfig
    from goal_cascade.orchestrator.execution_context import build_execution_context

    config = GoalConfig(
        providers=ProvidersConfig(
            enabled=["mock"],
            role_mapping={"producer": "mock"},
            synthesizer="mock",
        ),
    )

    with __import__("pytest").raises(ValueError) as exc_info:
        build_execution_context(config)

    msg = str(exc_info.value)
    assert "adversary" in msg
    assert "arbiter" in msg
    assert "critic" in msg


def test_provider_construction_failure_wraps_error() -> None:
    """Si _build_provider échoue, l'erreur est wrappée avec le nom du provider."""
    from unittest.mock import patch

    from goal_cascade.config import GoalConfig, ProvidersConfig
    from goal_cascade.orchestrator.execution_context import build_execution_context

    config = GoalConfig(
        providers=ProvidersConfig(
            enabled=["mock"],
            role_mapping={
                "producer": "mock",
                "critic": "mock",
                "adversary": "mock",
                "arbiter": "mock",
            },
            synthesizer="mock",
        ),
    )

    def _failing_build(name, **kwargs):
        raise RuntimeError("credentials invalid")

    with patch("goal_cascade.cli._build_provider", side_effect=_failing_build):
        with __import__("pytest").raises(ValueError, match="Échec de construction"):
            build_execution_context(config)


def test_create_executor_returns_cascade_executor() -> None:
    """create_executor() retourne un CascadeExecutor câblé avec le contexte."""
    from goal_cascade.config import GoalConfig, ProvidersConfig
    from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
    from goal_cascade.orchestrator.execution_context import build_execution_context

    config = GoalConfig(
        providers=ProvidersConfig(
            enabled=["mock"],
            role_mapping={
                "producer": "mock",
                "critic": "mock",
                "adversary": "mock",
                "arbiter": "mock",
            },
            synthesizer="mock",
        ),
    )

    ctx = build_execution_context(config)
    executor = ctx.create_executor()

    assert isinstance(executor, CascadeExecutor)
    assert executor.provider is ctx.provider
    assert executor.synthesizer_provider is ctx.synthesizer_provider