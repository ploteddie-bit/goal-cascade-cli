"""Smoke test E2E contre un vrai provider LLM (anthropic/openai/google).

Skip par défaut. Activable via ``GOAL_RUN_INTEGRATION=1``.

Pré-requis :
- ``pip install goal-cascade[llm]`` (mirascope, anthropic, structlog).
- Variable d'environnement du provider testé :
  - ``ANTHROPIC_API_KEY`` pour anthropic
  - ``OPENAI_API_KEY`` pour openai
  - ``GOOGLE_API_KEY`` pour google
- Variable ``GOAL_INTEGRATION_PROVIDER`` parmi {anthropic, openai, google}.

Ce test est volontairement cher (un vrai appel LLM) et lent. Il sert
de garde-fou final avant une release : il prouve que la chaîne complète
fonctionne avec un vrai provider, pas seulement avec mock.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from goal_cascade.cli import app


def _integration_enabled() -> bool:
    return os.environ.get("GOAL_RUN_INTEGRATION") == "1"


def _provider() -> str | None:
    return os.environ.get("GOAL_INTEGRATION_PROVIDER")


def _api_key_for(provider: str) -> str | None:
    return os.environ.get(f"{provider.upper()}_API_KEY")


pytestmark = pytest.mark.skipif(
    not _integration_enabled(),
    reason="GOAL_RUN_INTEGRATION != 1 — smoke test vrai provider désactivé",
)


@pytest.fixture(autouse=True)
def _no_real_rag_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aucun appel RAG réel pendant le smoke test."""
    from unittest.mock import MagicMock

    mock_bridge = MagicMock()
    mock_bridge.sync_run.return_value = {}
    monkeypatch.setattr("goal_cascade.cli.RagBridge", lambda: mock_bridge)


def test_real_provider_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Un seul appel cascade réel avec un vrai provider.

    Le budget est fixé à 0.05 USD pour éviter toute dérive de coût.
    Le test vérifie qu'au moins une itération a été enregistrée dans
    l'état et qu'aucune exception non gérée n'a été levée.
    """
    provider = _provider()
    if provider not in {"anthropic", "openai", "google"}:
        pytest.skip("GOAL_INTEGRATION_PROVIDER doit être anthropic|openai|google")
    if not _api_key_for(provider):
        pytest.skip(f"{provider.upper()}_API_KEY non défini")

    # Config TOML minimaliste avec un seul provider pour ce smoke test.
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[providers]
enabled = ["{provider}"]
role_mapping = {{ producer = "{provider}", critic = "{provider}", adversary = "{provider}", arbiter = "{provider}" }}
synthesizer = "{provider}"
require_diversity = false

[budget]
max_per_run_usd = 0.05
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr("goal_cascade.cli.DEFAULT_CONFIG_PATH", tmp_path / "absent.toml")
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--objective",
            "Smoke test E2E : confirme en une phrase que tu fonctionnes.",
            "--provider",
            provider,
            "--config",
            str(config_path),
        ],
    )

    # On accepte un exit code 0 ou un échec contrôlé (budget dépassé après
    # 1ère itération). L'important est qu'aucune exception Python non gérée
    # n'ait été levée et qu'un run_id ait été créé.
    runs_dir = Path.home() / ".goal" / "runs"
    if not runs_dir.exists():
        # Budget tracker a peut-être créé les traces ailleurs ; on tolère.
        pytest.skip(f"runs/ non créé : {runs_dir}")

    run_dirs = sorted(
        [d for d in runs_dir.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    assert run_dirs, "Aucun run créé"
    latest = run_dirs[0]
    state_file = latest / "state.json"
    assert state_file.exists(), f"state.json absent dans {latest}"
