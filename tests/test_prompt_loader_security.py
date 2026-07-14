"""Tests de sécurité du PromptLoader (audit B1-B5).

Couvre :
- B1 : Pas de traversal de chemin (.., /, \\, ~)
- B2 : Hiérarchie respectée (projet > utilisateur > package)
- B3 : Jinja2 sandboxing (pas de __import__, pas d'exécution code)
- B4 : Erreur claire si template manquant
- B5 : Variables de contexte typées (StrictUndefined)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import SecurityError, UndefinedError

from goal_cascade.orchestrator.prompt_loader import (
    InvalidTemplateNameError,
    PromptLoader,
    PromptNotFoundError,
)

# ── B1 : Traversal de chemin ────────────────────────────────────


class TestB1PathTraversal:
    """B1 : Le nom du template est sanitizé."""

    @pytest.mark.parametrize(
        "malicious_name",
        [
            "../../../etc/passwd",
            "..%2f..%2fetc%2fpasswd",
            "/etc/passwd",
            "~/secret",
            "..\\..\\windows\\system32",
            "templates/../../../secret",
        ],
    )
    def test_rejects_path_traversal(self, malicious_name: str) -> None:
        loader = PromptLoader()
        with pytest.raises(InvalidTemplateNameError, match="invalide"):
            loader.load(malicious_name)

    def test_template_source_also_validates(self) -> None:
        loader = PromptLoader()
        with pytest.raises(InvalidTemplateNameError):
            loader.template_source("../../../etc/passwd")


# ── B2 : Hiérarchie ─────────────────────────────────────────────


class TestB2Hierarchy:
    """B2 : Projet > utilisateur > package."""

    def test_project_overrides_user(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "project" / ".goal" / "prompts"
        project_dir.mkdir(parents=True)
        (project_dir / "test_hierarchy.j2").write_text("PROJECT", encoding="utf-8")

        user_dir = tmp_path / "user" / ".goal" / "prompts"
        user_dir.mkdir(parents=True)
        (user_dir / "test_hierarchy.j2").write_text("USER", encoding="utf-8")

        loader = PromptLoader(extra_paths=[project_dir, user_dir])
        result = loader.load("test_hierarchy.j2")
        assert result.strip() == "PROJECT"

    def test_search_paths_order(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom"
        custom.mkdir()
        loader = PromptLoader(extra_paths=[custom])
        paths = loader.search_paths
        # Le chemin custom doit être en premier
        assert paths[0] == custom.resolve()


# ── B3 : Jinja2 sandboxing ──────────────────────────────────────


class TestB3Sandboxing:
    """B3 : Pas d'exécution de code arbitraire dans les templates."""

    def test_blocks_class_attribute_access(self, tmp_path: Path) -> None:
        """Un template ne peut pas accéder à __class__ pour exécuter du code."""
        malicious = tmp_path / "evil.j2"
        malicious.write_text(
            "{{ ''.__class__.__mro__[1].__subclasses__() }}",
            encoding="utf-8",
        )
        loader = PromptLoader(extra_paths=[tmp_path])
        with pytest.raises((SecurityError, UndefinedError)):
            loader.load("evil.j2")

    def test_blocks_import(self, tmp_path: Path) -> None:
        """Un template ne peut pas importer des modules."""
        malicious = tmp_path / "import_evil.j2"
        malicious.write_text(
            "{% import 'os' as os %}{{ os.system('whoami') }}",
            encoding="utf-8",
        )
        loader = PromptLoader(extra_paths=[tmp_path])
        with pytest.raises((SecurityError, UndefinedError)):
            loader.load("import_evil.j2")


# ── B4 : Erreur claire si manquant ──────────────────────────────


class TestB4MissingTemplate:
    """B4 : PromptNotFoundError avec les chemins recherchés."""

    def test_error_contains_template_name(self, tmp_path: Path) -> None:
        loader = PromptLoader(extra_paths=[tmp_path])
        with pytest.raises(PromptNotFoundError) as exc_info:
            loader.load("nonexistent_template.j2")
        assert "nonexistent_template.j2" in str(exc_info.value)

    def test_error_contains_searched_paths(self, tmp_path: Path) -> None:
        loader = PromptLoader(extra_paths=[tmp_path])
        with pytest.raises(PromptNotFoundError) as exc_info:
            loader.load("missing.j2")
        assert hasattr(exc_info.value, "searched")
        assert len(exc_info.value.searched) > 0

    def test_error_name_attribute(self, tmp_path: Path) -> None:
        loader = PromptLoader(extra_paths=[tmp_path])
        with pytest.raises(PromptNotFoundError) as exc_info:
            loader.load("absent.j2")
        assert exc_info.value.name == "absent.j2"


# ── B5 : Variables strictes ─────────────────────────────────────


class TestB5StrictUndefined:
    """B5 : Une variable inexistante produit une erreur, pas une string vide."""

    def test_missing_variable_raises(self, tmp_path: Path) -> None:
        template = tmp_path / "strict_test.j2"
        template.write_text("Hello {{ nonexistent_var }}", encoding="utf-8")
        loader = PromptLoader(extra_paths=[tmp_path])
        with pytest.raises((SecurityError, UndefinedError)):
            loader.load("strict_test.j2")

    def test_provided_variable_works(self, tmp_path: Path) -> None:
        template = tmp_path / "ok_test.j2"
        template.write_text("Hello {{ name }}", encoding="utf-8")
        loader = PromptLoader(extra_paths=[tmp_path])
        result = loader.load("ok_test.j2", name="World")
        assert "Hello World" in result
