"""Tests d'intégration pour la commande goal resume.

Vérifie :
1. Un run inexistant retourne une erreur claire (exit_code != 0).
2. Un resume bloqué quand le budget est dépassé.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from goal_cascade.cli import app
from goal_cascade.orchestrator.budget_tracker import BudgetExceeded


runner = CliRunner()


# ── Test 1 : run inexistant ──────────────────────────────────────


class TestResumeNonexistentRun:
    """Un run inexistant doit retourner une erreur claire."""

    def test_resume_nonexistent_run_returns_clear_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """goal resume sur un run_id absent doit quitter avec un code != 0."""
        # Rediriger GOAL_HOME vers un répertoire vide pour garantir l'absence
        monkeypatch.setenv("GOAL_HOME", str(tmp_path))

        result = runner.invoke(app, ["resume", "run-inexistant-xyz"])

        assert result.exit_code != 0, (
            f"exit_code devrait être != 0 pour un run inexistant, "
            f"reçu {result.exit_code}"
        )


# ── Test 2 : budget dépassé ──────────────────────────────────────


class TestResumeBudgetExceeded:
    """Le resume doit être bloqué quand le coût dépasse le budget."""

    def test_resume_blocked_when_budget_exceeded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Simule un état avec coût > budget et vérifie que le resume échoue."""
        # Créer un checkpoint factice pour passer la vérification initiale
        run_id = "run-budget-test"
        checkpoint_dir = tmp_path / "runs" / run_id / ".checkpoints"
        checkpoint_dir.mkdir(parents=True)
        (checkpoint_dir / "checkpoint.db").write_text("fake", encoding="utf-8")

        # Rediriger GOAL_HOME vers tmp_path
        monkeypatch.setenv("GOAL_HOME", str(tmp_path))

        # Monkeypatch CascadeExecutor.resume pour lever BudgetExceeded,
        # simulant un état où accumulated_cost > max_per_run_usd.
        from goal_cascade.orchestrator import cascade_executor

        def _fake_resume(self, run_id, **kwargs):
            raise BudgetExceeded(
                run_id=run_id,
                accumulated=100.0,
                limit=0.50,
                scope="per_run",
            )

        monkeypatch.setattr(
            cascade_executor.CascadeExecutor, "resume", _fake_resume
        )

        result = runner.invoke(app, ["resume", run_id])

        assert result.exit_code != 0, (
            f"exit_code devrait être != 0 quand le budget est dépassé, "
            f"reçu {result.exit_code}"
        )
