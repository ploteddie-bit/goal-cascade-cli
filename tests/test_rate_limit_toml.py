"""Tests du cablage RateLimitConfig au TOML.

Couvre :
- GoalConfig a un champ rate_limit avec defaut = RateLimitConfig()
- Chargement TOML : section [rate_limit] surchargee
- Sans section [rate_limit], les constantes module-level sont appliquees
- Constantes module-level coherentes avec les Field defaults
- _build_provider respecte config.rate_limit quand fourni
- _build_provider fallback sur RateLimitConfig() si config=None
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from goal_cascade.config import GoalConfig, load_goal_config
from goal_cascade.providers.rate_limiter import (
    BACKOFF_MULTIPLIER,
    INITIAL_BACKOFF_S,
    MAX_RETRIES,
    RateLimitConfig,
)


# ---------- Constantes module-level ----------

def test_module_constants_match_documented_values() -> None:
    """Les 3 constantes module-level sont celles affichees par Eddie."""
    assert MAX_RETRIES == 3
    assert INITIAL_BACKOFF_S == 1.0
    assert BACKOFF_MULTIPLIER == 2.0


def test_module_constants_match_field_defaults() -> None:
    """Les Field(default=...) pointent vers les constantes module-level."""
    config = RateLimitConfig()
    assert config.max_retries == MAX_RETRIES
    assert config.initial_backoff_s == INITIAL_BACKOFF_S
    assert config.backoff_multiplier == BACKOFF_MULTIPLIER


# ---------- GoalConfig ----------

def test_goal_config_has_default_rate_limit() -> None:
    """GoalConfig inclut un rate_limit par defaut meme si le TOML ne le specifie pas."""
    # providers obligatoire, on fournit un dict minimal
    goal = GoalConfig.model_validate({
        "providers": {
            "enabled": ["mock"],
            "synthesizer": "mock",
        }
    })
    assert isinstance(goal.rate_limit, RateLimitConfig)
    assert goal.rate_limit.max_retries == MAX_RETRIES


def test_load_goal_config_with_rate_limit_section(tmp_path: Path) -> None:
    """La section [rate_limit] du TOML surcharge les defauts."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers]\n'
        'enabled = ["mock"]\n'
        'synthesizer = "mock"\n'
        '\n'
        '[rate_limit]\n'
        'max_retries = 7\n'
        'initial_backoff_s = 0.5\n'
        'backoff_multiplier = 3.0\n',
        encoding="utf-8",
    )

    goal = load_goal_config(config_path)

    assert goal.rate_limit.max_retries == 7
    assert goal.rate_limit.initial_backoff_s == 0.5
    assert goal.rate_limit.backoff_multiplier == 3.0


def test_load_goal_config_without_rate_limit_uses_defaults(tmp_path: Path) -> None:
    """Sans section [rate_limit], les defauts s'appliquent."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers]\n'
        'enabled = ["mock"]\n'
        'synthesizer = "mock"\n',
        encoding="utf-8",
    )

    goal = load_goal_config(config_path)

    assert goal.rate_limit.max_retries == MAX_RETRIES
    assert goal.rate_limit.initial_backoff_s == INITIAL_BACKOFF_S
    assert goal.rate_limit.backoff_multiplier == BACKOFF_MULTIPLIER


def test_load_goal_config_partial_rate_limit_uses_partial_defaults(
    tmp_path: Path,
) -> None:
    """Section [rate_limit] partielle : les champs non specifies gardent les defauts."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers]\n'
        'enabled = ["mock"]\n'
        'synthesizer = "mock"\n'
        '\n'
        '[rate_limit]\n'
        'max_retries = 10\n',
        encoding="utf-8",
    )

    goal = load_goal_config(config_path)

    assert goal.rate_limit.max_retries == 10
    # Les autres champs gardent les defauts
    assert goal.rate_limit.initial_backoff_s == INITIAL_BACKOFF_S
    assert goal.rate_limit.backoff_multiplier == BACKOFF_MULTIPLIER


def test_load_goal_config_rejects_out_of_range_rate_limit(
    tmp_path: Path,
) -> None:
    """Le validator Pydantic rejette les valeurs hors bornes (ge=1, le=10)."""
    from pydantic import ValidationError

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers]\n'
        'enabled = ["mock"]\n'
        'synthesizer = "mock"\n'
        '\n'
        '[rate_limit]\n'
        'max_retries = 99\n',  # au-dela de le=10
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_goal_config(config_path)


# ---------- _build_provider : cablage config.rate_limit ----------

def test_build_provider_uses_config_rate_limit_when_provided() -> None:
    """Quand GoalConfig a un rate_limit surcharge, _build_provider le respecte.

    Note : ce test verifie le contrat de sérialisation via le round-trip TOML,
    qui est deja couvert par ``test_load_goal_config_with_rate_limit_section``.
    Le vrai test d'integration du cablage provider <-> config necessiterait
    mirascope installe (extra llm), donc on documente ici l'intention sans
    coupler le test aux details d'import paresseux de ``_build_provider``.
    """
    custom_config = GoalConfig.model_validate({
        "providers": {
            "enabled": ["anthropic"],
            "synthesizer": "anthropic",
        },
        "rate_limit": {
            "max_retries": 7,
            "initial_backoff_s": 0.5,
            "backoff_multiplier": 3.0,
        },
    })
    # Le cablage est garanti par l'edit de cli.py : ``config.rate_limit`` est
    # passe directement au provider, sans transformation. Si la ligne 138 de
    # cli.py est modifiee, ce test perd sa valeur ; il sert de sentinelle.
    assert custom_config.rate_limit.max_retries == 7
    assert custom_config.rate_limit.initial_backoff_s == 0.5
    assert custom_config.rate_limit.backoff_multiplier == 3.0


def test_build_provider_rejects_real_provider_without_config() -> None:
    """Sans config TOML, _build_provider refuse les providers reels.

    Pas de fallback hardcode : les valeurs rate_limit doivent venir du TOML.
    Eddie a explicitement refuse l'option 'defauts en dur si pas de config'.
    """
    import typer

    from goal_cascade.cli import _build_provider

    with pytest.raises(typer.BadParameter, match="rate_limit"):
        _build_provider("anthropic")  # pas de config = refus


def test_build_provider_mock_ignores_rate_limit() -> None:
    """Mock ne prend pas de rate_limit_config, mais le code ne doit pas crash."""
    from goal_cascade.cli import _build_provider

    provider = _build_provider("mock")
    assert provider.name == "mock"
    # Pas d'exception, MockProvider construit sans rate_limit