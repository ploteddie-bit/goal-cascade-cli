"""Tests pour PromptLoader (load, list, override, erreurs) et template_source."""

from __future__ import annotations

from pathlib import Path

import pytest

from goal_cascade.orchestrator.prompt_loader import PromptLoader, PromptNotFoundError

# -- Tests demandés (chargeur hiérarchique) -----------------------------------


def test_load_from_package() -> None:
    """Charger iteration_1.j2 depuis le package et vérifier la présence de l'objectif."""
    loader = PromptLoader()
    result = loader.load(
        "iteration_1.j2",
        objective="Écrire un poème sur Python",
        previous_output="",
        last_synthesis="",
        audience="Débutants",
        constraints="",
        artifacts="",
    )
    assert "Écrire un poème sur Python" in result


def test_load_from_user_override(tmp_path: Path) -> None:
    """Un template dans extra_paths doit être prioritaire sur le package."""
    custom_dir = tmp_path / ".goal" / "prompts"
    custom_dir.mkdir(parents=True)
    (custom_dir / "custom_test.j2").write_text("TEMPLATE PERSONNALISE : {{ objective }}\n")

    loader = PromptLoader(extra_paths=[custom_dir])
    result = loader.load("custom_test.j2", objective="Test override")
    assert "TEMPLATE PERSONNALISE" in result
    assert "Test override" in result


def test_load_raises_on_missing() -> None:
    """Un template inexistant doit lever PromptNotFoundError."""
    loader = PromptLoader()
    with pytest.raises(PromptNotFoundError) as exc_info:
        loader.load("ce_template_n_existe_pas.j2")
    assert "ce_template_n_existe_pas.j2" in str(exc_info.value)


def test_list_templates() -> None:
    """list_templates() doit contenir au minimum les templates du package."""
    loader = PromptLoader()
    templates = loader.list_templates()
    for expected in ("iteration_1.j2", "synthesis.j2"):
        assert expected in templates, f"{expected} manquant dans {templates}"


# -- Tests existants (PromptNotFoundError + template_source) -------------------


class TestPromptNotFoundError:
    """Tests sur l'exception PromptNotFoundError."""

    def test_stores_name_and_searched_paths(self) -> None:
        paths = [Path("/a"), Path("/b")]
        err = PromptNotFoundError(name="missing.j2", searched=paths)

        assert err.name == "missing.j2"
        assert err.searched == paths

    def test_message_contains_template_name(self) -> None:
        err = PromptNotFoundError(name="foo.j2", searched=[Path("/x")])

        assert "foo.j2" in str(err)

    def test_message_contains_searched_paths(self) -> None:
        err = PromptNotFoundError(name="bar.j2", searched=[Path("/x"), Path("/y")])

        msg = str(err)
        assert "/x" in msg
        assert "/y" in msg

    def test_is_file_not_found_error(self) -> None:
        err = PromptNotFoundError(name="nope.j2", searched=[])

        assert isinstance(err, FileNotFoundError)


class TestTemplateSource:
    """Tests sur PromptLoader.template_source."""

    def test_template_source_returns_path_for_known_template(self) -> None:
        loader = PromptLoader()
        result = loader.template_source("iteration_1.j2")

        assert result is not None
        assert isinstance(result, Path)
        assert result.is_file()

    def test_template_source_returns_none_for_missing_template(self) -> None:
        loader = PromptLoader()
        result = loader.template_source("this_template_does_not_exist_xyz.j2")

        assert result is None
