from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from goal_cascade.cli import app


@pytest.fixture()
def absent_default_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Garantit que le CLI démarre sans config par défaut existante.

    Le home peut contenir un ~/.goal/config.toml sur la machine de
    l'utilisateur ; on force un chemin manifestement absent pour isoler
    le test.
    """

    missing = tmp_path / "absent-config.toml"
    assert not missing.exists()
    monkeypatch.setattr("goal_cascade.cli.DEFAULT_CONFIG_PATH", missing)
    return missing


def test_cli_shows_degraded_effective_mapping_without_external_provider_calls(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[providers]
enabled = ["mock"]
role_mapping = { producer = "mock", critic = "openai", adversary = "google", arbiter = "google" }
synthesizer = "mock"
require_diversity = false
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["run", "--objective", "Test config", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert "Config chargée" in result.output
    assert "Mode dégradé" in result.output
    assert "critic" in result.output
    assert "openai" in result.output
    assert "auto-switch" in result.output
    assert "mock" in result.output


def test_cli_strict_config_fails_before_run(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[providers]
enabled = ["mock"]
role_mapping = { producer = "mock", critic = "openai", adversary = "google", arbiter = "google" }
synthesizer = "mock"
require_diversity = true
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["run", "--objective", "Test config", "--config", str(config_path)],
    )

    assert result.exit_code != 0
    assert "require_diversity" in result.output


def test_cli_legacy_provider_mode_still_works_without_config(
    absent_default_config: Path,
) -> None:
    """Mode legacy : sans --config et sans config par défaut existante."""

    result = CliRunner().invoke(
        app,
        ["run", "--objective", "Test legacy", "--provider", "mock"],
    )

    assert result.exit_code == 0
    assert "Provider : Mock" in result.output


def test_cli_explicit_missing_config_reports_clear_error(
    absent_default_config: Path,
    tmp_path: Path,
) -> None:
    """Un --config PATH explicitement absent doit donner une erreur CLI claire.

    Le traceback brut ``FileNotFoundError`` n'est pas acceptable : on attend
    un message utilisateur contenant ``Config introuvable`` et un exit code
    non nul.
    """

    missing_config = tmp_path / "does-not-exist.toml"
    assert not missing_config.exists()

    result = CliRunner().invoke(
        app,
        ["run", "--objective", "x", "--config", str(missing_config)],
    )

    assert result.exit_code != 0
    assert "Config introuvable" in result.output
    assert "FileNotFoundError" not in result.output
