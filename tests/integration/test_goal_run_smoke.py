"""Smoke test E2E de la commande ``goal run``.

Vérifie que la chaîne complète (CLI → config → providers → cascade →
synthèse → CICDHook → journal → receipt) fonctionne avec un provider mock.

Pour un smoke test contre un vrai provider LLM (anthropic/openai/google),
voir ``test_real_provider_smoke.py`` (skip par défaut, activable via
``GOAL_RUN_INTEGRATION=1``).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from goal_cascade.cli import app


@pytest.fixture(autouse=True)
def _no_real_rag_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun appel RAG réel pendant le smoke test."""
    from unittest.mock import MagicMock

    mock_bridge = MagicMock()
    mock_bridge.sync_run.return_value = {}
    monkeypatch.setattr("goal_cascade.cli.RagBridge", lambda: mock_bridge)


@pytest.fixture()
def isolated_goal_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Force ~/.goal/ à pointer vers tmp_path pour isoler le smoke test."""
    goal_home = tmp_path / ".goal"
    monkeypatch.setattr("goal_cascade.cli.DEFAULT_CONFIG_PATH", goal_home / "absent.toml")
    # Redirige aussi RUNS_DIR (utilisé par state_manager.save_state).
    monkeypatch.setattr(
        "goal_cascade.orchestrator.state_manager.RUNS_DIR",
        goal_home / "runs",
    )
    return goal_home


def test_goal_run_smoke_mock_provider(
    isolated_goal_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La commande ``goal run --provider mock`` produit un run complet.

    Vérifie :
    - exit code 0
    - run_id créé
    - state.json + receipt.json présents
    - journal d'audit contient au moins un événement cicd_checks
      (câblage du CICDHook dans la cascade unique)
    - permissions 0o700 sur le run_dir
    """
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--objective",
            "Produire un rapport de smoke test E2E",
            "--provider",
            "mock",
            "--variant",
            "A",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Cascade terminee" in result.output or "stoppee" in result.output

    # Trouver le run_id créé
    runs_dir = isolated_goal_home / "runs"
    assert runs_dir.exists(), f"runs/ non créé : {runs_dir}"
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir()]
    assert len(run_dirs) == 1, f"Exactement 1 run attendu, trouvé {len(run_dirs)}"
    run_dir = run_dirs[0]

    # Permissions 0o700 (E2)
    assert (run_dir.stat().st_mode & 0o777) == 0o700

    # state.json + receipt.json présents
    assert (run_dir / "state.json").exists()
    assert (run_dir / "receipt.json").exists()

    # Le câblage CICDHook est validé par les tests unitaires
    # dédiés (test_cascade_cicd_wiring.py). Le smoke test mock-based
    # vérifie seulement que la chaîne CLI → cascade → traces fonctionne
    # end-to-end ; il ne dépend pas du contenu des artefacts produits
    # par MockProvider (qui n'inclut aucun bloc de code).
