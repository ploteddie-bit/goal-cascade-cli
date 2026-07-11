from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from goal_cascade.config import GoalConfig, ProvidersConfig, load_goal_config


def test_single_provider_duplicates_every_role_and_synthesizer() -> None:
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

    assert config.resolved_role_mapping == {
        "producer": "anthropic",
        "critic": "anthropic",
        "adversary": "anthropic",
        "arbiter": "anthropic",
    }
    assert config.resolved_synthesizer == "anthropic"
    assert config.degraded is True
    assert [item.role for item in config.adaptations] == [
        "critic",
        "adversary",
        "arbiter",
    ]


def test_fallback_uses_lower_tier_not_alphabetical_first() -> None:
    config = ProvidersConfig(
        enabled=["google", "openai"],
        role_mapping={
            "producer": "openai",
            "critic": "anthropic",
            "adversary": "google",
            "arbiter": "anthropic",
        },
        synthesizer="anthropic",
    )

    assert config.resolved_role_mapping["producer"] == "openai"
    assert config.resolved_role_mapping["critic"] == "openai"
    assert config.resolved_role_mapping["adversary"] == "google"
    assert config.resolved_role_mapping["arbiter"] == "google"
    assert config.resolved_synthesizer == "openai"


def test_optimal_config_has_no_adaptation() -> None:
    config = ProvidersConfig(
        enabled=["anthropic", "openai", "google"],
        role_mapping={
            "producer": "anthropic",
            "critic": "openai",
            "adversary": "google",
            "arbiter": "google",
        },
        synthesizer="anthropic",
    )

    assert config.degraded is False
    assert config.adaptations == []
    assert config.resolved_role_mapping == config.role_mapping
    assert config.resolved_synthesizer == "anthropic"


def test_require_diversity_rejects_degraded_resolution() -> None:
    with pytest.raises(ValidationError) as error:
        ProvidersConfig(
            enabled=["anthropic"],
            role_mapping={
                "producer": "anthropic",
                "critic": "openai",
                "adversary": "google",
                "arbiter": "google",
            },
            synthesizer="anthropic",
            require_diversity=True,
        )

    assert "require_diversity" in str(error.value)


def test_zero_enabled_is_rejected() -> None:
    with pytest.raises(ValidationError) as error:
        ProvidersConfig(
            enabled=[],
            role_mapping={"producer": "anthropic"},
            synthesizer="anthropic",
        )

    assert "at least 1" in str(error.value).lower() or "au moins" in str(error.value).lower()


def test_load_goal_config_reads_toml(tmp_path: Path) -> None:
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

    config = load_goal_config(config_path)

    assert isinstance(config, GoalConfig)
    assert config.providers.resolved_role_mapping["critic"] == "anthropic"
    assert config.providers.degraded is True


def test_mapping_rows_preserve_configured_and_effective_values() -> None:
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

    rows = {row.role: row for row in config.mapping_rows()}

    assert rows["producer"].configured == "anthropic"
    assert rows["producer"].effective == "anthropic"
    assert rows["producer"].auto_switched is False
    assert rows["critic"].configured == "openai"
    assert rows["critic"].effective == "anthropic"
    assert rows["critic"].auto_switched is True
    assert rows["synthesizer"].configured == "anthropic"
    assert rows["synthesizer"].effective == "anthropic"
