"""Hook CI/CD pour vérification déterministe des artefacts."""

import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

from goal_cascade.schemas.models import ImmutableArtifact, InterfaceContract

# Mapping artifact_type -> commande de vérification déterministe
CHECKERS: dict[str, str] = {
    "code": "python -m py_compile {path}",
    "json_schema": "python -m json.tool {path}",
}


@dataclass
class DeterministicCheckResult:
    """Résultat d'une vérification déterministe sur un ensemble d'artefacts."""

    passed: bool
    failures: list[dict[str, Any]] = field(default_factory=list)
    method: str = "deterministic"


class CICDHook:
    """Hook CI/CD exécutant des vérifications déterministes sur les artefacts."""

    def __init__(
        self,
        custom_checkers: dict[str, Callable[[str], dict[str, Any] | None]] | None = None,
    ) -> None:
        self._custom_checkers: dict[str, Callable[[str], dict[str, Any] | None]] = (
            custom_checkers or {}
        )

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
            checker_cmd = CHECKERS.get(artifact.artifact_type)
            if checker_cmd is None:
                continue

            result = self._run_checker(checker_cmd, artifact)
            if result is not None:
                failures.append(result)

        return DeterministicCheckResult(
            passed=len(failures) == 0,
            failures=failures,
            method="deterministic",
        )

    def _run_checker(
        self, cmd: str, artifact: ImmutableArtifact
    ) -> dict[str, Any] | None:
        """Exécute une commande de vérification sur un artefact.

        Args:
            cmd: La commande à exécuter (avec {path} comme placeholder).
            artifact: L'artefact à vérifier.

        Returns:
            Un dict décrivant l'échec, ou None si la vérification passe.
        """
        command = cmd.format(path=artifact.path)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {
                "artifact": artifact.path,
                "type": artifact.artifact_type,
                "error": "timeout after 30s",
            }

        if proc.returncode != 0:
            return {
                "artifact": artifact.path,
                "type": artifact.artifact_type,
                "returncode": proc.returncode,
                "stderr": proc.stderr.strip(),
            }

        return None
