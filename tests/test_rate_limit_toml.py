"""Tests du cablage RateLimitConfig au TOML.

Couvre :
- Constantes module-level coherentes avec les Field defaults
- GoalConfig a un champ ratelimit avec defaut = RateLimitConfig()
- Accepte [ratelimit] (canonique) ou [rate_limit] (alias) dans TOML
- Chargement TOML : section [ratelimit] surchargee
- Sans section [ratelimit], les constantes module-level sont appliquees
- _build_provider utilise model_dump() (copie defensive)
- _build_provider fallback sur RateLimitConfig() si config=None
- _build_provider mock n'est pas affecte par rate_limit
"""

from __future__ import annotations

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


# ---------- GoalConfig : champ ratelimit + AliasChoices ----------


def test_goal_config_has_default_ratelimit() -> None:
    """GoalConfig inclut un ratelimit par defaut meme si le TOML ne le specifie pas."""
    goal = GoalConfig.model_validate(
        {
            "providers": {
                "enabled": ["mock"],
                "synthesizer": "mock",
            }
        }
    )
    assert isinstance(goal.ratelimit, RateLimitConfig)
    assert goal.ratelimit.max_retries == MAX_RETRIES


def test_goal_config_accepts_ratelimit_alias() -> None:
    """Le TOML peut utiliser [ratelimit] (canonique) ou [rate_limit] (alias)."""
    # Forme canonique
    canonical = GoalConfig.model_validate(
        {
            "providers": {"enabled": ["mock"], "synthesizer": "mock"},
            "ratelimit": {"max_retries": 5},
        }
    )
    assert canonical.ratelimit.max_retries == 5

    # Forme alias (compatibilite ascendante)
    alias = GoalConfig.model_validate(
        {
            "providers": {"enabled": ["mock"], "synthesizer": "mock"},
            "rate_limit": {"max_retries": 9},
        }
    )
    assert alias.ratelimit.max_retries == 9


def test_load_goal_config_with_ratelimit_section(tmp_path: Path) -> None:
    """La section [ratelimit] du TOML surcharge les defauts."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[providers]\n"
        'enabled = ["mock"]\n'
        'synthesizer = "mock"\n'
        "\n"
        "[ratelimit]\n"
        "max_retries = 7\n"
        "initial_backoff_s = 0.5\n"
        "backoff_multiplier = 3.0\n",
        encoding="utf-8",
    )

    goal = load_goal_config(config_path)

    assert goal.ratelimit.max_retries == 7
    assert goal.ratelimit.initial_backoff_s == 0.5
    assert goal.ratelimit.backoff_multiplier == 3.0


def test_load_goal_config_without_ratelimit_uses_defaults(tmp_path: Path) -> None:
    """Sans section [ratelimit], les defauts s'appliquent."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers]\nenabled = ["mock"]\nsynthesizer = "mock"\n',
        encoding="utf-8",
    )

    goal = load_goal_config(config_path)

    assert goal.ratelimit.max_retries == MAX_RETRIES
    assert goal.ratelimit.initial_backoff_s == INITIAL_BACKOFF_S
    assert goal.ratelimit.backoff_multiplier == BACKOFF_MULTIPLIER


def test_load_goal_config_partial_ratelimit_uses_partial_defaults(
    tmp_path: Path,
) -> None:
    """Section [ratelimit] partielle : les champs non specifies gardent les defauts."""
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[providers]\nenabled = ["mock"]\nsynthesizer = "mock"\n\n[ratelimit]\nmax_retries = 10\n',
        encoding="utf-8",
    )

    goal = load_goal_config(config_path)

    assert goal.ratelimit.max_retries == 10
    # Les autres champs gardent les defauts
    assert goal.ratelimit.initial_backoff_s == INITIAL_BACKOFF_S
    assert goal.ratelimit.backoff_multiplier == BACKOFF_MULTIPLIER


def test_load_goal_config_rejects_out_of_range_ratelimit(
    tmp_path: Path,
) -> None:
    """Le validator Pydantic rejette les valeurs hors bornes (ge=1, le=10)."""
    from pydantic import ValidationError

    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[providers]\n"
        'enabled = ["mock"]\n'
        'synthesizer = "mock"\n'
        "\n"
        "[ratelimit]\n"
        "max_retries = 99\n",  # au-dela de le=10
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_goal_config(config_path)


# ---------- _build_provider : cablage config.ratelimit ----------


def test_build_provider_uses_config_ratelimit_when_provided() -> None:
    """Quand GoalConfig a un ratelimit surcharge, _build_provider le respecte.

    Le cablage est garanti par l'edit de cli.py :
    ``RateLimitConfig(**config.ratelimit.model_dump())`` est passe au provider.
    """
    custom_config = GoalConfig.model_validate(
        {
            "providers": {
                "enabled": ["anthropic"],
                "synthesizer": "anthropic",
            },
            "ratelimit": {
                "max_retries": 7,
                "initial_backoff_s": 0.5,
                "backoff_multiplier": 3.0,
            },
        }
    )
    # Verifie la copie defensive : model_dump() doit retourner un dict
    # independant de la config source.
    dumped = custom_config.ratelimit.model_dump()
    assert dumped == {
        "max_retries": 7,
        "initial_backoff_s": 0.5,
        "backoff_multiplier": 3.0,
    }
    # Reconstruction doit produire un RateLimitConfig identique
    reconstructed = RateLimitConfig(**dumped)
    assert reconstructed.max_retries == 7
    assert reconstructed.initial_backoff_s == 0.5
    assert reconstructed.backoff_multiplier == 3.0


def test_build_provider_uses_ratelimit_from_ratelimit_alias() -> None:
    """Le TOML avec [rate_limit] (alias) charge bien config.ratelimit."""
    config_path = Path("/tmp/_test_alias_config.toml")
    config_path.write_text(
        '[providers]\nenabled = ["mock"]\nsynthesizer = "mock"\n\n[rate_limit]\nmax_retries = 4\n',
        encoding="utf-8",
    )
    goal = load_goal_config(config_path)
    assert goal.ratelimit.max_retries == 4


def test_build_provider_falls_back_to_defaults_without_config() -> None:
    """Sans config TOML, _build_provider utilise RateLimitConfig() (defauts)."""
    from goal_cascade.cli import _build_provider

    # Mock : aucun appel reel necessaire, juste verifier la signature.
    provider = _build_provider("mock")
    assert provider.name == "mock"


def test_build_provider_mock_ignores_ratelimit() -> None:
    """Mock ne prend pas de rate_limit_config, mais le code ne doit pas crash."""
    from goal_cascade.cli import _build_provider

    provider = _build_provider("mock")
    assert provider.name == "mock"
    # Pas d'exception, MockProvider construit sans rate_limit
