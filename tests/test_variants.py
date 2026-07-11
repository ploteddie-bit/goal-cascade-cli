from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from goal_cascade.cli import app
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.providers.mock import MockProvider
from goal_cascade.schemas.models import Variant


def test_mock_prefers_initial_objective_over_synthesis_heading() -> None:
    provider = MockProvider()
    prompt = "OBJECTIF INITIAL :\nObjectif exact\n\nSYNTHÈSE ORIENTÉE OBJECTIF :\n{}"

    assert provider._extract_objective(prompt) == "Objectif exact"


def test_variant_b_uses_technical_prompt() -> None:
    executor = CascadeExecutor(
        provider=MockProvider(),
        synthesizer_provider=MockProvider(),
    )
    state = executor.init_state("Écrire une fonction Python", Variant.B)

    prompt = executor._build_prompt(state, state.role_for_iteration(1))

    assert "développeur" in prompt.lower()
    assert "code" in prompt.lower()
    assert "rédacteur" not in prompt.lower()


def test_cli_rejects_unknown_variant() -> None:
    result = CliRunner().invoke(
        app,
        ["run", "--objective", "Test", "--variant", "C"],
    )

    assert result.exit_code != 0
    assert "Invalid value" in result.output or "invalide" in result.output.lower()


def test_cli_requires_explicit_small_model_for_kimi() -> None:
    for extra_args in [[], ["--synthesizer-model", "   "]]:
        result = CliRunner().invoke(
            app,
            ["run", "--objective", "Test", "--provider", "kimi-code", *extra_args],
        )

        assert result.exit_code != 0
        assert "Erreur : --synthesizer-model est requis avec un provider Kimi" in result.output
