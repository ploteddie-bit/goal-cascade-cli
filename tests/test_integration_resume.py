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
            f"exit_code devrait être != 0 pour un run inexistant, reçu {result.exit_code}"
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

        monkeypatch.setattr(cascade_executor.CascadeExecutor, "resume", _fake_resume)

        result = runner.invoke(app, ["resume", run_id])

        assert result.exit_code != 0, (
            f"exit_code devrait être != 0 quand le budget est dépassé, reçu {result.exit_code}"
        )


# ── Test 3 : resume finalise reçu + métadonnées + RAG ────────────


class TestResumeFinalization:
    """resume() doit finaliser comme run() : reçu, métadonnées, sync RAG."""

    def test_resume_finalizes_receipt_metadata_and_rag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Après un resume, receipt.json/run-metadata.json existent et le RAG
        est resynchronisé — l'angle mort corrigé (cascade_executor.resume)."""
        from unittest.mock import MagicMock

        from goal_cascade.orchestrator import state_manager
        from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
        from goal_cascade.providers.mock import MockProvider

        # Rediriger tout l'IO disque (runs, checkpoints, journal) vers tmp.
        runs_dir = tmp_path / "runs"
        monkeypatch.setattr(state_manager, "RUNS_DIR", runs_dir)

        rag_bridge = MagicMock()
        executor = CascadeExecutor(
            provider=MockProvider(),
            synthesizer_provider=MockProvider(),
            rag_bridge=rag_bridge,
        )

        # 1. Run initial (mock, hors ligne) : crée un vrai checkpoint SQLite.
        state = executor.init_state(objective="Test resume finalization")
        run_id = state.run_id
        executor.run(state, verbose=False)

        run_dir = runs_dir / run_id
        receipt_path = run_dir / "receipt.json"
        metadata_path = run_dir / "run-metadata.json"
        assert receipt_path.exists(), "run() doit d'abord finaliser (baseline)"
        assert rag_bridge.sync_run.call_count == 1

        # 2. Effacer les artefacts de finalisation et réinitialiser le spy.
        receipt_path.unlink()
        rag_bridge.sync_run.reset_mock()

        # 3. Resume : doit reconstruire le reçu, les métadonnées et re-sync RAG.
        executor.resume(run_id, verbose=False)

        assert receipt_path.exists(), "resume() doit re-générer receipt.json"
        assert metadata_path.exists(), "resume() doit finaliser les métadonnées"
        assert rag_bridge.sync_run.call_count == 1, "resume() doit appeler rag_bridge.sync_run"
        assert rag_bridge.sync_run.call_args.args[0] == run_id
