"""Hook CI/CD pour vérification déterministe des artefacts (spec V2 §11).

Pour le formel (types, schémas, tests), un outil déterministe est
supérieur à un LLM. Ce hook exécute les vérifications AVANT tout
appel LLM dans la cascade d'intégration.

Règle absolue : ne jamais déléguer au LLM une vérification qu'un
compilateur ou un linter peut faire à 100% de précision.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

from goal_cascade.schemas.models import ImmutableArtifact, InterfaceContract

# Type d'un vérificateur déterministe : reçoit un artefact, retourne
# un dict d'erreur ou None si la vérification passe.
CheckerFn = Callable[[ImmutableArtifact], dict[str, Any] | None]


def _run_checker(
    cmd: list[str],
    artifact: ImmutableArtifact,
    input_text: str | None = None,
) -> dict[str, Any] | None:
    """Exécute une commande de vérification de manière isolée.

    - Pas de ``shell=True`` (A3).
    - Le contenu utilisateur passe par ``input=`` ou par un fichier
      temporaire créé par le hook, jamais interpolé dans la commande (A2).
    - Timeout borné à 30 s (A1).
    - ``TimeoutExpired`` et ``FileNotFoundError`` sont attrapés et logués (A4).
    """
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "cicd_checker_timeout artifact_type=%s checker=%s",
            artifact.artifact_type,
            cmd[0],
        )
        return {
            "artifact_type": artifact.artifact_type,
            "checker": " ".join(cmd),
            "error": "timeout after 30s",
        }
    except FileNotFoundError as exc:
        logger.error(
            "cicd_checker_not_found artifact_type=%s checker=%s error=%s",
            artifact.artifact_type,
            cmd[0],
            str(exc),
        )
        return {
            "artifact_type": artifact.artifact_type,
            "checker": " ".join(cmd),
            "error": f"command not found: {cmd[0]}",
        }
    except Exception as exc:  # pragma: no cover - défense en profondeur
        logger.error(
            "cicd_checker_error artifact_type=%s checker=%s error=%s",
            artifact.artifact_type,
            cmd[0],
            str(exc),
        )
        return {
            "artifact_type": artifact.artifact_type,
            "checker": " ".join(cmd),
            "error": str(exc),
        }

    if proc.returncode != 0:
        error_msg = proc.stderr.strip() or proc.stdout.strip()
        logger.warning(
            "cicd_checker_failed artifact_type=%s checker=%s returncode=%d",
            artifact.artifact_type,
            cmd[0],
            proc.returncode,
        )
        return {
            "artifact_type": artifact.artifact_type,
            "checker": " ".join(cmd),
            "error": error_msg,
        }

    return None


def _check_python_code(artifact: ImmutableArtifact) -> dict[str, Any] | None:
    """Vérifie la syntaxe Python via ``py_compile``.

    Le contenu est écrit dans un fichier temporaire dont le chemin
    est contrôlé par le hook ; il n'est jamais interpolé dans une
    commande shell.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(artifact.content)
        tmp_path = tmp.name

    try:
        return _run_checker([sys.executable, "-m", "py_compile", tmp_path], artifact)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError as exc:
            logger.warning("cicd_temp_cleanup_failed path=%s error=%s", tmp_path, str(exc))


def _check_json_schema(artifact: ImmutableArtifact) -> dict[str, Any] | None:
    """Vérifie la validité JSON via ``json.tool`` en utilisant stdin."""
    return _run_checker(
        [sys.executable, "-m", "json.tool"],
        artifact,
        input_text=artifact.content,
    )


# Vérificateurs déterministes par défaut.
# Aucune commande n'interpole de contenu utilisateur (A2).
CHECKERS: dict[str, CheckerFn] = {
    "code": _check_python_code,
    "json_schema": _check_json_schema,
}


@dataclass
class DeterministicCheckResult:
    """Résultat d'une vérification déterministe sur un ensemble d'artefacts."""

    passed: bool
    failures: list[dict[str, Any]] = field(default_factory=list)
    method: str = "deterministic"


class CICDHook:
    """Hook CI/CD exécutant des vérifications déterministes sur les artefacts."""

    def __init__(self, custom_checkers: dict[str, CheckerFn] | None = None) -> None:
        self._checkers: dict[str, CheckerFn] = dict(CHECKERS)
        if custom_checkers:
            self._checkers.update(custom_checkers)

    def run_deterministic_checks(
        self,
        contract: InterfaceContract,
        artifacts: list[ImmutableArtifact],
    ) -> DeterministicCheckResult:
        """Exécute les vérifications déterministes sur une liste d'artefacts.

        Args:
            contract: Le contrat d'interface applicable.
            artifacts: La liste des artefacts immuables à vérifier.

        Returns:
            DeterministicCheckResult avec le statut global et les éventuels échecs.
        """
        failures: list[dict[str, Any]] = []

        for artifact in artifacts:
            checker = self._checkers.get(artifact.artifact_type)
            if checker is None:
                logger.debug("cicd_no_checker artifact_type=%s", artifact.artifact_type)
                continue

            try:
                result = checker(artifact)
            except Exception as exc:  # pragma: no cover - défense en profondeur
                logger.exception(
                    "cicd_checker_exception artifact_type=%s",
                    artifact.artifact_type,
                )
                result = {
                    "artifact_type": artifact.artifact_type,
                    "checker": artifact.artifact_type,
                    "error": f"checker crashed: {exc}",
                }

            if result is not None:
                failures.append(result)

        passed = len(failures) == 0
        if passed:
            logger.info("cicd_checks_passed artifacts=%d", len(artifacts))
        else:
            logger.warning(
                "cicd_checks_failed artifacts=%d failures=%d",
                len(artifacts),
                len(failures),
            )

        return DeterministicCheckResult(
            passed=passed,
            failures=failures,
            method="deterministic",
        )
