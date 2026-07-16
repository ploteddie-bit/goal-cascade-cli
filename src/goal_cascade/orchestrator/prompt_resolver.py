"""Résolveur de prompts avec support des overrides par run (O4 — Phase 5).

Charge les templates Jinja2 en cherchant d'abord un override dans
``~/.goal/runs/{id_cascade}/prompts/{role}.j2``, puis en fallback sur
le template par défaut du package.

L'override permet le "hot-reload" : modifier un fichier .j2 entre
deux itérations d'une cascade (ou pendant que la cascade est en cours)
sans redémarrer quoi que ce soit.

Sécurité : la résolution est strictement confinée à ``runs_dir`` (anti-path
traversal). Un nom de rôle ou un id de cascade malformé est rejeté.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from ..prompts import PromptLoader

logger = logging.getLogger(__name__)

# Regex pour valider id_cascade et nom de template (anti-path-traversal)
_RE_ID_CASCADE = re.compile(r"^[0-9a-f]{4,16}$")
_RE_NOM_TEMPLATE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")


class PromptResolutionError(Exception):
    """Erreur lors du chargement d'un prompt (id invalide, fichier absent, etc.)."""


class PromptResolver:
    """Charge un prompt Jinja2 avec override prioritaire par (run_id, role).

    Usage::

        resolver = PromptResolver(runs_dir=Path("~/.goal/runs"))
        template = resolver.charger("iteration_1.j2", id_cascade="aabbccdd")

    Si ``~/.goal/runs/aabbccdd/prompts/iteration_1.j2`` existe, son contenu
    est utilisé. Sinon, fallback sur le template par défaut du package.
    """

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self._loader = PromptLoader()

    def charger(self, nom_template: str, id_cascade: str | None = None) -> str:
        """Charge un prompt : override (si run_id fourni) puis défaut.

        Args:
            nom_template: nom du fichier .j2 (ex: "iteration_1.j2")
            id_cascade: identifiant du run (None = défaut uniquement)

        Returns:
            Contenu du template (texte brut, non rendu).

        Raises:
            PromptResolutionError: si nom_template ou id_cascade invalide.
        """
        if not _RE_NOM_TEMPLATE.match(nom_template.removesuffix(".j2")):
            raise PromptResolutionError(
                f"nom_template invalide : {nom_template!r}"
            )

        # 1. Cherche l'override du run
        if id_cascade is not None:
            if not _RE_ID_CASCADE.match(id_cascade):
                raise PromptResolutionError(
                    f"id_cascade invalide (format hex 4-16 attendu) : {id_cascade!r}"
                )
            chemin_override = (
                self.runs_dir / id_cascade / "prompts" / nom_template
            )
            if self._est_sous_runs_dir(chemin_override):
                if chemin_override.is_file():
                    logger.info(
                        "prompt_override_utilise run=%s template=%s",
                        id_cascade, nom_template,
                    )
                    return chemin_override.read_text(encoding="utf-8")

        # 2. Fallback : template par défaut du package
        try:
            source, _, _ = self._loader.env.loader.get_source(
                self._loader.env, nom_template
            )
            return source
        except Exception as exc:
            raise PromptResolutionError(
                f"Impossible de charger {nom_template!r} (ni override ni défaut) : {exc}"
            ) from exc

    def _est_sous_runs_dir(self, chemin: Path) -> bool:
        """Vérifie que ``chemin`` est bien sous ``runs_dir`` (anti-../).

        Empêche un override malicieux d'utiliser un chemin qui sort
        du répertoire de runs.
        """
        try:
            chemin.resolve().relative_to(self.runs_dir.resolve())
            return True
        except (ValueError, OSError):
            return False
