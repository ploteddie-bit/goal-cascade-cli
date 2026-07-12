"""Graphe de modules pour le multi-cascade.

Construit un DAG (Directed Acyclic Graph) de modules à partir de
FrozenSpec et InterfaceContract, avec calcul d'ordre topologique
et de batches parallèles.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from goal_cascade.schemas.models import FrozenSpec, InterfaceContract


class ModuleGraph:
    """Graphe acyclique dirigé de modules d'un multi-cascade."""

    def __init__(self) -> None:
        self._dag: nx.DiGraph = nx.DiGraph()
        self._specs: dict[str, FrozenSpec] = {}
        self._contracts: dict[str, InterfaceContract] = {}  # keyed by contract_id

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def add_module(self, module_id: str, spec: FrozenSpec) -> None:
        """Ajoute un nœud (module) au graphe."""
        if module_id in self._dag:
            raise ValueError(f"Module '{module_id}' déjà présent dans le graphe.")
        self._dag.add_node(module_id)
        self._specs[module_id] = spec

    def add_dependency(
        self,
        producer: str,
        consumer: str,
        contract: InterfaceContract,
    ) -> None:
        """Ajoute une arête producer → consumer avec un contrat d'interface."""
        for mid in (producer, consumer):
            if mid not in self._dag:
                raise ValueError(
                    f"Module '{mid}' absent du graphe. "
                    "Appelez add_module() avant add_dependency()."
                )
        self._dag.add_edge(producer, consumer, contract=contract)
        self._contracts[contract.contract_id] = contract

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_acyclic(self) -> None:
        """Vérifie que le graphe est acyclique.

        Raises:
            nx.HasACycle: si un cycle est détecté.
        """
        try:
            nx.find_cycle(self._dag)
        except nx.NetworkXNoCycle:
            return  # OK — pas de cycle
        raise nx.HasACycle("Le graphe de modules contient un cycle.")

    # ------------------------------------------------------------------
    # Parcours
    # ------------------------------------------------------------------

    def topological_order(self) -> list[str]:
        """Retourne les module_ids dans l'ordre topologique.

        Raises:
            nx.NetworkXUnfeasible: si le graphe contient un cycle.
        """
        self.validate_acyclic()
        return list(nx.topological_sort(self._dag))

    def parallel_batches(self) -> list[list[str]]:
        """Retourne les modules regroupés par niveaux d'exécution parallèle.

        Chaque batch contient des modules indépendants les uns des autres ;
        le batch N ne peut s'exécuter qu'après que le batch N-1 est terminé.

        Returns:
            Liste de listes de module_ids.
        """
        self.validate_acyclic()
        levels: dict[str, int] = {}
        for node in nx.topological_sort(self._dag):
            preds = [levels[p] for p in self._dag.predecessors(node)]
            levels[node] = (max(preds) + 1) if preds else 0

        max_level = max(levels.values()) if levels else -1
        batches: list[list[str]] = []
        for lvl in range(max_level + 1):
            batch = sorted(m for m, l in levels.items() if l == lvl)
            batches.append(batch)
        return batches

    # ------------------------------------------------------------------
    # Consultation
    # ------------------------------------------------------------------

    def get_contracts_for_module(self, module_id: str) -> list[InterfaceContract]:
        """Retourne tous les contrats où module_id est producteur ou consommateur."""
        if module_id not in self._dag:
            raise ValueError(f"Module '{module_id}' absent du graphe.")
        result: list[InterfaceContract] = []
        for _, _, data in self._dag.edges(data=True):
            contract: InterfaceContract = data["contract"]
            if contract.producer_module == module_id or contract.consumer_module == module_id:
                result.append(contract)
        return result

    def leaf_modules(self) -> list[str]:
        """Retourne les modules sans successeurs (feuilles du DAG)."""
        return sorted(n for n in self._dag.nodes if self._dag.out_degree(n) == 0)

    def integration_module(self) -> str | None:
        """Retourne le module d'intégration (racine unique du DAG) ou None.

        La racine est le nœud de degré entrant 0. Si plusieurs existent,
        on retourne None (pas de module d'intégration unique).
        """
        roots = [n for n in self._dag.nodes if self._dag.in_degree(n) == 0]
        if len(roots) == 1:
            return roots[0]
        return None

    # ------------------------------------------------------------------
    # Sérialisation
    # ------------------------------------------------------------------

    @classmethod
    def from_plan_file(cls, plan_path: str | Path) -> ModuleGraph:
        """Construit un ModuleGraph depuis un fichier plan JSON.

        Format attendu::

            {
                "modules": [
                    {"module_id": "modA", "spec": { ... FrozenSpec ... }},
                    ...
                ],
                "contracts": [
                    {"producer": "modA", "consumer": "modB", "contract": { ... InterfaceContract ... }},
                    ...
                ]
            }
        """
        path = Path(plan_path)
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        graph = cls()
        for entry in data.get("modules", []):
            spec = FrozenSpec(**entry["spec"])
            graph.add_module(entry["module_id"], spec)
        for entry in data.get("contracts", []):
            contract = InterfaceContract(**entry["contract"])
            graph.add_dependency(entry["producer"], entry["consumer"], contract)

        graph.validate_acyclic()
        return graph

    def to_plan_dict(self) -> dict:
        """Exporte le graphe sous forme de dictionnaire sérialisable."""
        modules = []
        for mid in sorted(self._specs):
            modules.append({
                "module_id": mid,
                "spec": self._specs[mid].model_dump(),
            })
        contracts = []
        for src, tgt, data in sorted(self._dag.edges(data=True)):
            contracts.append({
                "producer": src,
                "consumer": tgt,
                "contract": data["contract"].model_dump(),
            })
        return {"modules": modules, "contracts": contracts}
