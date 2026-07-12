"""Exécuteur multi-cascade — orchestration de modules interdépendants.

Exécute un graphe de modules par batches topologiques, vérifie les
contrats d'interface entre producteur et consommateur, puis lance
une cascade d'intégration finale.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from goal_cascade.multicascade.interface_checker import InterfaceChecker
from goal_cascade.multicascade.module_graph import ModuleGraph
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.schemas.models import (
    CascadeState,
    FrozenSpec,
    InterfaceContract,
    Verdict,
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
    """La cascade d'intégration finale a terminé en état d'échec."""

    def __init__(self, state: CascadeState) -> None:
        self.state = state
        summary = state.last_error or state.status
        super().__init__(f"Intégration en échec : {summary}")


# ------------------------------------------------------------------
# Exécuteur principal
# ------------------------------------------------------------------


@dataclass
class MultiCascadeExecutor:
    """Orchestrateur multi-cascade.

    Exécute chaque module dans l'ordre topologique (par batches
    parallèles quand les dépendances le permettent), vérifie les
    contrats d'interface, puis lance une cascade d'intégration.
    """

    module_graph: ModuleGraph
    cascade_executor: CascadeExecutor
    interface_checker: InterfaceChecker

    # Résultats cumulés (peuplés après run_all)
    _results: dict[str, CascadeState] = field(
        default_factory=dict, init=False, repr=False
    )

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
            ModuleFailedError: si un module termine sans verdict STOP.
        """
        self._results.clear()
        batches = self.module_graph.parallel_batches()

        for batch_index, batch in enumerate(batches):
            for module_id in batch:
                spec = self._get_spec(module_id)
                state = self._run_single_module(
                    module_id=module_id,
                    spec=spec,
                    verbose=verbose,
                )
                self._results[module_id] = state

                # Vérifier les contrats d'interface avec les producteurs
                self._check_interfaces(module_id, state)

                if state.status == "failed" or (
                    state.final_verdict is not None
                    and state.final_verdict.decision == "CONTINUE"
                ):
                    raise ModuleFailedError(module_id, state)

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
            IntegrationFailedError: si l'intégration échoue.
        """
        results = module_results if module_results is not None else self._results
        if not results:
            raise ValueError(
                "Aucun résultat de module disponible. "
                "Appelez run_all() avant run_integration()."
            )

        integration_objective = self._build_integration_objective(results)
        integration_spec = self._build_integration_spec(results)

        run_id = f"integration-{uuid.uuid4().hex[:8]}"
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

        if final_state.status == "failed" or (
            final_state.final_verdict is not None
            and final_state.final_verdict.decision == "CONTINUE"
        ):
            raise IntegrationFailedError(final_state)

        return final_state

    # ------------------------------------------------------------------
    # Méthodes internes
    # ------------------------------------------------------------------

    def _get_spec(self, module_id: str) -> FrozenSpec:
        """Récupère la FrozenSpec d'un module depuis le graphe."""
        contracts = self.module_graph.get_contracts_for_module(module_id)
        # On récupère la spec directement depuis le graphe interne
        # via le serialisation plan (le module_graph ne expose pas
        # directement get_spec, mais to_plan_dict le contient).
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

    def _check_interfaces(
        self,
        module_id: str,
        state: CascadeState,
    ) -> None:
        """Vérifie les contrats d'interface où module_id est consommateur."""
        contracts = self.module_graph.get_contracts_for_module(module_id)
        for contract in contracts:
            if contract.consumer_module != module_id:
                continue
            producer_id = contract.producer_module
            producer_state = self._results.get(producer_id)
            if producer_state is None:
                # Le producteur n'a pas encore été exécuté (ne devrait
                # pas arriver dans un ordre topologique valide).
                continue
            self.interface_checker.check(
                contract=contract,
                producer_state=producer_state,
                consumer_state=state,
            )

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
            parts.append(
                f"- {module_id} : {synthesis_summary or state.objective}"
            )
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
