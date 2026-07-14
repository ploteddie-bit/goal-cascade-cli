"""Chargeur de prompts Jinja2 hiérarchique.

Recherche les templates dans trois niveaux de priorité (du plus haut au plus bas) :
    1. ./.goal/prompts/  — prompts du projet courant
    2. ~/.goal/prompts/  — prompts utilisateur globaux
    3. <package>/prompts/ — prompts embarqués dans le package

Le premier répertoire contenant le template demandé gagne.
Les chemins inexistants sont filtrés à l'initialisation.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader, StrictUndefined, TemplateNotFound
from jinja2.sandbox import SandboxedEnvironment

try:
    import structlog

    _logger: Any = structlog.get_logger(__name__)
except ImportError:
    _logger = logging.getLogger(__name__)

# Chemins par défaut (hors package)
DEFAULT_SEARCH_PATHS: list[Path] = [
    Path.cwd() / ".goal" / "prompts",
    Path.home() / ".goal" / "prompts",
]

# Chemin des prompts embarqués dans le package
_PACKAGE_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class PromptNotFoundError(FileNotFoundError):
    """Le template demandé n'existe dans aucun des répertoires de recherche."""

    def __init__(self, name: str, searched: Sequence[Path]) -> None:
        self.name = name
        self.searched = list(searched)
        paths = "\n  ".join(str(p) for p in self.searched) or "(aucun)"
        super().__init__(f"Template '{name}' introuvable. Chemins cherchés :\n  {paths}")


class InvalidTemplateNameError(ValueError):
    """Le nom de template contient des caractères ou séquences dangereuses."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(
            f"Nom de template invalide '{name}' : {reason}. "
            "Seuls les caractères alphanumériques, _, - et . sont autorisés."
        )


# Caractères interdits dans un nom de template (sécurité B1)
_FORBIDDEN_PATTERNS = ("..", "/", "\\", "\x00")


def _validate_template_name(name: str) -> None:
    """Valide qu'un nom de template ne contient pas de traversal de chemin.

    Sécurité B1 : empêche ../../etc/passwd et les chemins absolus.
    """
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern in name:
            raise InvalidTemplateNameError(name, f"contient '{pattern}'")
    if name.startswith("~"):
        raise InvalidTemplateNameError(name, "commence par '~'")
    # Vérifier que le nom ne pointe pas hors du répertoire après résolution
    # par FileSystemLoader (double safety net)
    if name != Path(name).name and not name.endswith(".j2"):
        # Path("a.j2").name == "a.j2" → OK
        # Path("../a.j2").name == "a.j2" mais ".." déjà catché ci-dessus
        pass


class PromptLoader:
    """Chargeur de prompts Jinja2 à résolution hiérarchique.

    Parameters
    ----------
    extra_paths :
        Chemins additionnels à placer *avant* les chemins par défaut
        dans l'ordre de recherche. Les doublons et les chemins inexistants
        sont ignorés.
    """

    def __init__(self, extra_paths: list[Path] | None = None) -> None:
        # Construire la liste complète : extras > cwd > home > package
        raw: list[Path] = list(extra_paths or [])
        raw.extend(DEFAULT_SEARCH_PATHS)
        raw.append(_PACKAGE_PROMPTS_DIR)

        # Dédupliquer en gardant l'ordre + filtrer les chemins inexistants
        seen: set[str] = set()
        self._search_paths: list[Path] = []
        for p in raw:
            resolved = p.resolve()
            key = str(resolved)
            if key not in seen and resolved.is_dir():
                seen.add(key)
                self._search_paths.append(resolved)

        _logger.debug(
            "prompt_loader.init",
            search_paths=[str(p) for p in self._search_paths],
        )

        # Sécurité B3 : SandboxedEnvironment empêche __import__, __class__,
        # accès aux attributs privés et exécution de code arbitraire.
        # Sécurité B5 : StrictUndefined lève si une variable n'existe pas
        # au lieu de produire une string vide silencieusement.
        self._env = SandboxedEnvironment(
            loader=FileSystemLoader([str(p) for p in self._search_paths]),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

    # -- API publique -------------------------------------------------------

    def load(self, prompt_name: str, **context: Any) -> str:
        """Charge un template et le rend avec *context*.

        Parameters
        ----------
        prompt_name :
            Nom du fichier template (ex. ``"iteration_1.j2"``).
        **context :
            Variables injectées dans le template Jinja2.

        Raises
        ------
        InvalidTemplateNameError
            Si le nom contient des séquences de traversal (.., /, \\).
        PromptNotFoundError
            Si le template n'existe dans aucun répertoire de recherche.
        """
        _validate_template_name(prompt_name)
        try:
            template = self._env.get_template(prompt_name)
        except TemplateNotFound as exc:
            raise PromptNotFoundError(
                name=exc.name or prompt_name,
                searched=self._search_paths,
            ) from exc
        return template.render(**context)

    def list_templates(self) -> list[str]:
        """Retourne la liste de tous les templates disponibles (tous niveaux)."""
        return sorted(self._env.list_templates())

    def template_source(self, prompt_name: str) -> Path | None:
        """Retourne le chemin complet du premier fichier correspondant à *prompt_name*.

        Retourne ``None`` si le template n'existe pas.
        """
        _validate_template_name(prompt_name)
        for search_dir in self._search_paths:
            candidate = search_dir / prompt_name
            if candidate.is_file():
                return candidate
        return None

    # -- Propriété en lecture seule -----------------------------------------

    @property
    def search_paths(self) -> list[Path]:
        """Chemins de recherche effectifs (après filtrage)."""
        return list(self._search_paths)
