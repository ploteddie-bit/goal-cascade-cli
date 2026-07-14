"""Tests du ModuleGraph — DAG de modules multi-cascade.

Couvre :
- Ajout de modules et ordre topologique
- Batches parallèles
- Détection de cycle
- Chargement depuis un fichier plan JSON
- Export en dictionnaire (to_plan_dict)
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import pytest

from goal_cascade.multicascade.module_graph import ModuleGraph
from goal_cascade.schemas.models import FrozenSpec, InterfaceContract


# ── Helpers ──────────────────────────────────────────────────────


def _make_spec(name: str, objective: str = "obj") -> FrozenSpec:
    """Crée un FrozenSpec minimal pour les tests."""
    return FrozenSpec(
        module_name=name,
        objective=objective,
        invariants=[{"description": f"invariant de {name}"}],
    )


def _make_contract(cid: str, producer: str, consumer: str) -> InterfaceContract:
    """Crée un InterfaceContract minimal pour les tests."""
    return InterfaceContract(
        contract_id=cid,
        producer_module=producer,
        consumer_module=consumer,
        output_description=f"sortie de {producer}",
        input_description=f"entrée de {consumer}",
    )


# ── 1. Ordre topologique ────────────────────────────────────────


class TestTopologicalOrder:
    def test_add_module_and_topological_order(self) -> None:
        """A → B → C donne l'ordre [A, B, C]."""
        g = ModuleGraph()
        g.add_module("A", _make_spec("A"))
        g.add_module("B", _make_spec("B"))
        g.add_module("C", _make_spec("C"))
        g.add_dependency("A", "B", _make_contract("c1", "A", "B"))
        g.add_dependency("B", "C", _make_contract("c2", "B", "C"))

        order = g.topological_order()
        assert order == ["A", "B", "C"]


# ── 2. Batches parallèles ───────────────────────────────────────


class TestParallelBatches:
    def test_parallel_batches(self) -> None:
        """A→B et C indépendant → batches [[A, C], [B]]."""
        g = ModuleGraph()
        g.add_module("A", _make_spec("A"))
        g.add_module("B", _make_spec("B"))
        g.add_module("C", _make_spec("C"))
        g.add_dependency("A", "B", _make_contract("c1", "A", "B"))
        # C est indépendant — pas de dépendance

        batches = g.parallel_batches()
        assert batches == [["A", "C"], ["B"]]


# ── 3. Détection de cycle ───────────────────────────────────────


class TestCycleDetection:
    def test_cycle_detection(self) -> None:
        """A → B → A lève HasACycle (cycle détecté)."""
        g = ModuleGraph()
        g.add_module("A", _make_spec("A"))
        g.add_module("B", _make_spec("B"))
        g.add_dependency("A", "B", _make_contract("c1", "A", "B"))
        g.add_dependency("B", "A", _make_contract("c2", "B", "A"))

        with pytest.raises(nx.HasACycle):
            g.validate_acyclic()


# ── 4. Chargement depuis plan.json ──────────────────────────────


class TestFromPlanFile:
    def test_from_plan_file(self, tmp_path: Path) -> None:
        """Charge un plan JSON et vérifie les modules présents."""
        plan = {
            "modules": [
                {
                    "module_id": "modA",
                    "spec": {
                        "module_name": "ModuleA",
                        "objective": "produire des données",
                        "invariants": [{"description": "sortie non vide"}],
                    },
                },
                {
                    "module_id": "modB",
                    "spec": {
                        "module_name": "ModuleB",
                        "objective": "transformer les données",
                        "invariants": [{"description": "format JSON"}],
                    },
                },
            ],
            "contracts": [
                {
                    "producer": "modA",
                    "consumer": "modB",
                    "contract": {
                        "contract_id": "c-ab",
                        "producer_module": "modA",
                        "consumer_module": "modB",
                        "output_description": "données brutes",
                        "input_description": "données à transformer",
                    },
                },
            ],
        }
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(plan), encoding="utf-8")

        g = ModuleGraph.from_plan_file(plan_file)
        order = g.topological_order()

        assert set(order) == {"modA", "modB"}
        assert order.index("modA") < order.index("modB")


# ── 5. Export to_plan_dict ──────────────────────────────────────


class TestToPlanDict:
    def test_to_plan_dict(self) -> None:
        """Exporte un graphe en dict et vérifie la structure."""
        g = ModuleGraph()
        g.add_module("X", _make_spec("X", "objectif X"))
        g.add_module("Y", _make_spec("Y", "objectif Y"))
        g.add_dependency("X", "Y", _make_contract("c-xy", "X", "Y"))

        d = g.to_plan_dict()

        assert "modules" in d
        assert "contracts" in d
        assert len(d["modules"]) == 2
        assert len(d["contracts"]) == 1

        module_ids = {m["module_id"] for m in d["modules"]}
        assert module_ids == {"X", "Y"}

        contract = d["contracts"][0]
        assert contract["producer"] == "X"
        assert contract["consumer"] == "Y"
        assert contract["contract"]["contract_id"] == "c-xy"
