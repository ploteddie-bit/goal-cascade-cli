"""Vérification hybride des contrats d'interface entre modules.

Phase 1 : vérifications déterministes via CICDHook (syntaxe, schéma JSON).
Phase 2 (v1 placeholder) : vérifications LLM (cohérence sémantique,
  compatibilité de format, couverture des cas d'erreur).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from goal_cascade.orchestrator.cicd_hook import CICDHook, DeterministicCheckResult
from goal_cascade.schemas.models import CascadeState, InterfaceContract


@dataclass
class CheckFailure:
    """Échec individuel d'une vérification d'interface."""

    artifact_type: str
    checker: str
    error: str
    method: str


@dataclass
class CheckResult:
    """Résultat global d'une vérification d'interface."""

    passed: bool
    failures: list[CheckFailure] = field(default_factory=list)
    method: str = "hybrid"


class InterfaceChecker:
    """Vérificateur hybride de contrats d'interface.

    Temps 1 — déterministe : passe les artefacts au travers du CICDHook
      pour validation syntaxique (py_compile, json.tool, etc.).
    Temps 2 — LLM (placeholder v1) : analyse sémantique à implémenter
      dans une version ultérieure.

    Args:
        cicd_hook: Instance de CICDHook pour les vérifications déterministes.
            Si None, un hook par défaut est créé.
    """

    def __init__(self, cicd_hook: CICDHook | None = None) -> None:
        self._cicd = cicd_hook or CICDHook()

    def check(
        self,
        contracts: list[InterfaceContract],
        module_states: dict[str, CascadeState],
        current_module_id: str,
    ) -> CheckResult:
        """Vérifie tous les contrats impliquant le module courant.

        Args:
            contracts: Liste complète des contrats d'interface.
            module_states: États des cascades indexés par module_id.
            current_module_id: Identifiant du module en cours d'exécution.

        Returns:
            CheckResult avec le statut global et les éventuels échecs.
        """
        all_failures: list[CheckFailure] = []

        relevant = [
            c
            for c in contracts
            if c.producer_module == current_module_id
            or c.consumer_module == current_module_id
        ]

        for contract in relevant:
            # Temps 1 : déterministe — toujours avant toute phase LLM (A5).
            # Si le formel échoue, on retourne immédiatement sans déléguer
            # au LLM une vérification qu'un outil déterministe peut faire.
            det_result = self._run_deterministic_checks(contract, module_states)
            for det_fail in det_result.failures:
                all_failures.append(
                    CheckFailure(
                        artifact_type=det_fail.get("type", "unknown"),
                        checker="cicd_hook",
                        error=det_fail.get("error", det_fail.get("stderr", "unknown")),
                        method="deterministic",
                    )
                )

            if all_failures:
                return CheckResult(
                    passed=False,
                    failures=all_failures,
                )

            # Temps 2 : LLM (placeholder v1)
            # TODO(v2) : invoquer le LLM pour vérifier la cohérence sémantique
            #   entre producer et consumer (format, invariants, error_cases).
            #   Ne JAMAIS être appelé si la phase déterministe a échoué.

        return CheckResult(
            passed=len(all_failures) == 0,
            failures=all_failures,
        )

    def _run_deterministic_checks(
        self,
        contract: InterfaceContract,
        module_states: dict[str, CascadeState],
    ) -> DeterministicCheckResult:
        """Délègue les vérifications déterministes au CICDHook.

        Rassemble les artefacts des deux modules liés par le contrat
        (producteur et consommateur) et les soumet au hook CI/CD.

        Args:
            contract: Le contrat d'interface à vérifier.
            module_states: États des cascades indexés par module_id.

        Returns:
            DeterministicCheckResult avec le statut global et les éventuels échecs.
        """
        artifacts = []
        for module_id in (contract.producer_module, contract.consumer_module):
            state = module_states.get(module_id)
            if state is not None:
                artifacts.extend(state.artifacts)

        return self._cicd.run_deterministic_checks(contract, artifacts)
