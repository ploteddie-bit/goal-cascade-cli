"""Tests des anti-patterns et règles de résilience (spec V2 §17-18).

F1. Pas de cache sémantique intra-cascade.
F2. Historique brut jamais transmis (mode normal).
F3. Limite absolue de 5 itérations.
F4. Doute profite au STOP : verdict non parsable → STOP par défaut.
F5. Diversité multi-provider : refus si tous les rôles sur même famille.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from goal_cascade.cli import app
from goal_cascade.config import ProvidersConfig
from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.schemas.models import Variant


class _UnparseableVerdictProvider(BaseProvider):
    """Provider simulant un arbitre qui ne produit pas de JSON valide."""

    def __init__(self, arbiter_text: str) -> None:
        self.arbiter_text = arbiter_text
        self._name = "unparseable"

    @property
    def name(self) -> str:
        return self._name

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        if role == "producer":
            text = "Draft initial"
        elif role == "synthesizer":
            text = json.dumps(
                {
                    "objective": "Objectif de test",
                    "key_decisions": ["Décision conservée"],
                    "uncertainties": [],
                    "next_instruction": "Poursuivre",
                },
                ensure_ascii=False,
            )
        elif role == "arbiter":
            text = self.arbiter_text
        else:
            text = f"Rapport {role}"
        return LLMResponse(text=text, provider=self._name, model=f"test-{tier}")


class TestF4DefaultStopOnAmbiguousVerdict:
    """Doute profite au STOP : tout verdict non parsable force l'arrêt."""

    @pytest.mark.parametrize(
        "arbiter_text",
        [
            "Pas de JSON du tout",
            "**Verdict** : STOP\nJUSTIFICATION : ancien format textuel",
            '{"decision":"STOP","justification":"ok"}\ntexte après le verdict',
            '{"wrapper":{"decision":"STOP","justification":"imbriqué"}}',
        ],
    )
    def test_ambiguous_verdict_defaults_to_stop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arbiter_text: str
    ) -> None:
        monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
        executor = CascadeExecutor(
            provider=_UnparseableVerdictProvider(arbiter_text),
            synthesizer_provider=_UnparseableVerdictProvider(arbiter_text),
        )

        state = executor.run(
            executor.init_state("Objectif de test", Variant.A),
            verbose=False,
        )

        assert state.status == "stopped"
        assert state.final_verdict is not None
        assert state.final_verdict.decision == "STOP"
        assert "non parsable" in state.final_verdict.justification.lower()


class TestF5SingleProviderFamilyRefused:
    """Refus explicite quand tous les rôles tombent dans la même famille."""

    def test_single_non_mock_provider_is_diversity_failure(self) -> None:
        config = ProvidersConfig(
            enabled=["anthropic"],
            role_mapping={
                "producer": "anthropic",
                "critic": "openai",
                "adversary": "google",
                "arbiter": "google",
            },
            synthesizer="anthropic",
        )

        assert config.diversity_failure is True
        assert config.degraded is True

    def test_multiple_families_is_not_diversity_failure(self) -> None:
        config = ProvidersConfig(
            enabled=["anthropic", "openai"],
            role_mapping={
                "producer": "anthropic",
                "critic": "openai",
                "adversary": "openai",
                "arbiter": "anthropic",
            },
            synthesizer="anthropic",
        )

        assert config.diversity_failure is False

    def test_mock_only_is_allowed_for_tests(self) -> None:
        config = ProvidersConfig(
            enabled=["mock"],
            role_mapping={
                "producer": "mock",
                "critic": "openai",
                "adversary": "google",
                "arbiter": "google",
            },
            synthesizer="mock",
        )

        assert config.diversity_failure is False

    def test_cli_refuses_single_non_mock_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            """
[providers]
enabled = ["anthropic"]
role_mapping = { producer = "anthropic", critic = "openai", adversary = "google", arbiter = "google" }
synthesizer = "anthropic"
require_diversity = false
""".strip(),
            encoding="utf-8",
        )

        # Isoler le home pour ne pas charger un ~/.goal/config.toml réel.
        monkeypatch.setattr("goal_cascade.cli.DEFAULT_CONFIG_PATH", tmp_path / "absent.toml")

        result = CliRunner().invoke(
            app,
            ["run", "--objective", "Test diversité", "--config", str(config_path)],
        )

        assert result.exit_code != 0
        assert "Diversité" in result.output
        assert "même famille" in result.output
