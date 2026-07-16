"""Exécuteur multi-cascade — orchestration de modules interdépendants.

Exécute un graphe de modules par batches topologiques, vérifie les
contrats d'interface entre producteur et consommateur, puis lance
une cascade d'intégration finale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from goal_cascade.multicascade.interface_checker import (
    CheckResult,
    InterfaceChecker,
)
from goal_cascade.multicascade.module_graph import ModuleGraph
from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.budget_tracker import BudgetTracker
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.schemas.models import (
    CascadeState,
    FrozenSpec,
)

# ------------------------------------------------------------------
# Erreurs métier
# ------------------------------------------------------------------


class ModuleFailedError(Exception):
    """Un module du multi-cascade a terminé en état d'échec."""

    def __init__(self, module_id: str, state: CascadeState) -> None:
        self.module_id = module_id
        self.state = state
        summary = state.last_error or state.status
        super().__init__(f"Module '{module_id}' en échec : {summary}")


class IntegrationFailedError(Exception):
    """La cascade d'intégration finale a terminé en état d'échec.

    Si déclenchée après 5 cycles infructueux, le message indique
    explicitement qu'il faut revoir le découpage Phase 1 (spec §7.4).
    """

    def __init__(
        self,
        state: CascadeState | None = None,
        message: str | None = None,
    ) -> None:
        self.state = state
        if message is not None:
            super().__init__(message)
        elif state is not None:
            summary = state.last_error or state.status
            super().__init__(f"Intégration en échec : {summary}")
        else:
            super().__init__("Intégration en échec (état inconnu)")


class InterfaceViolationError(Exception):
    """Un contrat d'interface entre modules est violé."""

    def __init__(self, module_id: str, check_result: CheckResult) -> None:
        self.module_id = module_id
        self.check_result = check_result
        failures = "; ".join(
            f"{f.artifact_type} ({f.checker}): {f.error}" for f in check_result.failures
        )
        super().__init__(f"Interface invalide pour '{module_id}' : {failures}")


# ------------------------------------------------------------------
# Exécuteur principal
# ------------------------------------------------------------------


@dataclass
class MultiCascadeExecutor:
    """Orchestrateur multi-cascade.

    Exécute chaque module dans l'ordre topologique (par batches
    parallèles quand les dépendances le permettent), vérifie les
    contrats d'interface, puis lance une cascade d'intégration.

    Args:
        module_graph: Graphe acyclique des modules et de leurs contrats.
        cascade_executor: Exécuteur de cascade individuelle.
        interface_checker: Vérificateur de contrats d'interface.
        budget_tracker: Kill switch budgétaire global pour l'ensemble
            du multi-cascade. Si fourni, le budget est vérifié avant
            chaque module et avant l'intégration.
    """

    module_graph: ModuleGraph
    cascade_executor: CascadeExecutor
    interface_checker: InterfaceChecker = field(default_factory=InterfaceChecker)
    budget_tracker: BudgetTracker | None = None

    # Résultats cumulés (peuplés après run_all)
    _results: dict[str, CascadeState] = field(default_factory=dict, init=False, repr=False)
    # Coût total accumulé par tous les modules exécutés
    _total_cost: float = field(default=0.0, init=False, repr=False)
    # Compteur de cycles d'intégration (spec §7.4 — limite 5 avant revoir Phase 1)
    _integration_cycles: int = field(default=0, init=False, repr=False)

    # Limite absolue de cycles d'intégration (spec §7.4)
    INTEGRATION_MAX_CYCLES: int = 5

    # ------------------------------------------------------------------
    # Exécution complète
    # ------------------------------------------------------------------

    def run_all(
        self,
        verbose: bool = True,
    ) -> dict[str, CascadeState]:
        """Exécute tous les modules par batches topologiques.

        Args:
            verbose: journalisation détaillée.

        Returns:
            Dictionnaire {module_id: CascadeState final du module}.

        Raises:
            nx.HasACycle: si le graphe contient un cycle (C1).
            BudgetExceeded: si le budget global est dépassé (C2).
            ModuleFailedError: si un module termine sans verdict STOP (C3).
            InterfaceViolationError: si un contrat d'interface est violé (C6).
        """
        self._results.clear()
        self._total_cost = 0.0
        self._integration_cycles = 0  # Reset du compteur d'intégration

        # C1 : validation acyclique explicite avant toute exécution.
        self.module_graph.validate_acyclic()
        batches = self.module_graph.parallel_batches()
        logger.info(
            "multi_cascade_start modules=%d batches=%d",
            len(self.module_graph._dag.nodes),
            len(batches),
        )

        for batch_index, batch in enumerate(batches):
            logger.info(
                "multi_cascade_batch_start batch=%d/%d modules=%s",
                batch_index + 1,
                len(batches),
                batch,
            )

            for module_id in batch:
                # C2 : vérification budgétaire avant chaque module.
                if self.budget_tracker is not None:
                    self.budget_tracker.check_budget(module_id, self._total_cost)

                spec = self._get_spec(module_id)
                state = self._run_single_module(
                    module_id=module_id,
                    spec=spec,
                    verbose=verbose,
                )
                self._results[module_id] = state

                # C2 : enregistrement du coût du module dans le tracker global.
                if self.budget_tracker is not None:
                    self.budget_tracker.record(state.accumulated_cost)
                    self._total_cost += state.accumulated_cost

                # C3 : arrêt propre sur échec avec checkpoint.
                if state.status == "failed" or (
                    state.final_verdict is not None and state.final_verdict.decision == "CONTINUE"
                ):
                    state_manager.save_state(state)
                    raise ModuleFailedError(module_id, state)

            # C6 : vérification des contrats d'interface APRÈS chaque batch.
            self._check_batch_interfaces(batch)

        logger.info(
            "multi_cascade_all_modules_done total=%d cost=%.4f",
            len(self._results),
            self._total_cost,
        )
        return dict(self._results)

    # ------------------------------------------------------------------
    # Cascade d'intégration
    # ------------------------------------------------------------------

    def run_integration(
        self,
        module_results: dict[str, CascadeState] | None = None,
        verbose: bool = True,
    ) -> CascadeState:
        """Lance une cascade d'intégration sur les résultats combinés.

        L'objectif d'intégration est construit à partir des objectifs
        et synthèses de tous les modules. Le FrozenSpec d'intégration
        agrège les invariants de chaque module.

        Args:
            module_results: résultats par module (défaut : self._results).
            verbose: journalisation détaillée.

        Returns:
            CascadeState de l'intégration finale.

        Raises:
            ValueError: si aucun résultat de module n'est disponible.
            BudgetExceeded: si le budget global est dépassé avant l'intégration.
            IntegrationFailedError: si l'intégration échoue.
        """
        results = module_results if module_results is not None else self._results
        if not results:
            raise ValueError(
                "Aucun résultat de module disponible. Appelez run_all() avant run_integration()."
            )

        # A3 : Compteur de cycles d'intégration (spec §7.4 — limite 5).
        self._integration_cycles += 1
        if self._integration_cycles > self.INTEGRATION_MAX_CYCLES:
            raise IntegrationFailedError(
                state=None,
                message=(
                    f"Limite de {self.INTEGRATION_MAX_CYCLES} cycles d'intégration atteinte "
                    "sans succès. Le découpage Phase 1 est probablement mal conçu : "
                    "les frontières entre modules sont mal placées. "
                    "Revenir à Phase 1 et redécouper."
                ),
            )

        # C2 : vérification budgétaire avant la cascade d'intégration.
        if self.budget_tracker is not None:
            self.budget_tracker.check_budget("integration", self._total_cost)

        integration_objective = self._build_integration_objective(results)
        integration_spec = self._build_integration_spec(results)

        run_id = f"integration-{uuid.uuid4().hex[:8]}"
        # C4 : limite de 5 itérations pour l'intégration.
        integration_state = CascadeState(
            run_id=run_id,
            objective=integration_objective,
            max_iterations=5,
        )

        final_state = self.cascade_executor.run(
            state=integration_state,
            audience="integration",
            constraints=f"FrozenSpec: {integration_spec.model_dump_json()}",
            verbose=verbose,
        )

        # C2 : enregistrement du coût d'intégration.
        if self.budget_tracker is not None:
            self.budget_tracker.record(final_state.accumulated_cost)
            self._total_cost += final_state.accumulated_cost

        # Succès : on reset le compteur pour les prochains appels éventuels.
        # Note: ne PAS reset sur "forced_stop" — c'est un échec où la cascade
        # a épuisé ses 5 itérations internes, l'utilisateur va typiquement retry
        # l'intégration depuis l'extérieur (donc on garde le compteur).
        if final_state.status == "stopped":
            self._integration_cycles = 0

        if final_state.status == "failed" or (
            final_state.final_verdict is not None
            and final_state.final_verdict.decision == "CONTINUE"
        ):
            raise IntegrationFailedError(final_state)

        logger.info(
            "multi_cascade_integration_done iterations=%d cost=%.4f",
            final_state.current_iteration,
            final_state.accumulated_cost,
        )
        return final_state

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    def _build_integration_objective(
        self,
        module_results: dict[str, CascadeState],
    ) -> str:
        """Construit l'objectif d'intégration à partir des modules."""
        parts: list[str] = []
        for module_id, state in module_results.items():
            synthesis_summary = ""
            if state.last_synthesis is not None:
                synthesis_summary = state.last_synthesis.objective
            parts.append(f"- {module_id} : {synthesis_summary or state.objective}")
        modules_text = "\n".join(parts)
        return (
            "Intégration des modules suivants :\n"
            f"{modules_text}\n\n"
            "Valider la cohérence globale et produire un rapport d'intégration."
        )

    def _build_integration_spec(
        self,
        module_results: dict[str, CascadeState],
    ) -> FrozenSpec:
        """Agrège les invariants de tous les modules en un FrozenSpec d'intégration."""
        from goal_cascade.schemas.models import Invariant

        aggregated_invariants: list[Invariant] = []
        for module_id, _state in module_results.items():
            spec = self._get_spec(module_id)
            for inv in spec.invariants:
                # Préfixer l'invariant avec le nom du module source
                aggregated_invariants.append(
                    Invariant(
                        description=f"[{module_id}] {inv.description}",
                        verified=False,
                    )
                )

        if not aggregated_invariants:
            aggregated_invariants.append(
                Invariant(
                    description="Vérifier la cohérence globale de l'intégration",
                    verified=False,
                )
            )

        return FrozenSpec(
            module_name="integration",
            objective="Valider l'intégration de tous les modules",
            invariants=aggregated_invariants,
        )

    def _get_spec(self, module_id: str) -> FrozenSpec:
        """Récupère la FrozenSpec d'un module depuis le graphe."""
        plan = self.module_graph.to_plan_dict()
        for entry in plan.get("modules", []):
            if entry["module_id"] == module_id:
                return FrozenSpec(**entry["spec"])
        raise KeyError(f"FrozenSpec introuvable pour le module '{module_id}'.")

    def _run_single_module(
        self,
        module_id: str,
        spec: FrozenSpec,
        verbose: bool,
    ) -> CascadeState:
        """Lance une cascade unique pour un module."""
        run_id = f"{module_id}-{uuid.uuid4().hex[:8]}"
        state = CascadeState(
            run_id=run_id,
            objective=spec.objective,
            max_iterations=5,
        )

        constraints = spec.model_dump_json()
        return self.cascade_executor.run(
            state=state,
            audience=module_id,
            constraints=f"FrozenSpec: {constraints}",
            verbose=verbose,
        )

    def _check_batch_interfaces(self, batch: list[str]) -> None:
        """Vérifie les contrats d'interface après qu'un batch est terminé (C6).

        Pour chaque module du batch, on vérifie les contrats où il est
        impliqué (producteur ou consommateur) en utilisant les états
        déjà accumulés dans ``self._results``.

        Args:
            batch: Liste des module_ids du batch terminé.

        Raises:
            InterfaceViolationError: si un contrat est formellement invalide.
        """
        for module_id in batch:
            contracts = self.module_graph.get_contracts_for_module(module_id)
            if not contracts:
                continue

            result = self.interface_checker.check(
                contracts=contracts,
                module_states=self._results,
                current_module_id=module_id,
            )

            if not result.passed:
                logger.error(
                    "interface_check_failed module=%s failures=%d",
                    module_id,
                    len(result.failures),
                )
                raise InterfaceViolationError(module_id, result)

            logger.info(
                "interface_check_passed module=%s contracts=%d",
                module_id,
                len(contracts),
            )
