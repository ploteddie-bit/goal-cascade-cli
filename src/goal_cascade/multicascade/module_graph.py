"""Graphe de modules pour le multi-cascade.

Construit un DAG (Directed Acyclic Graph) de modules à partir de
FrozenSpec et InterfaceContract, avec calcul d'ordre topologique
et de batches parallèles.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import networkx as nx

from goal_cascade.schemas.models import FrozenSpec, InterfaceContract, Invariant
from goal_cascade.schemas.plan import CascadePlan, DependencySpec, ModuleSpec

logger = logging.getLogger(__name__)


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
                    f"Module '{mid}' absent du graphe. Appelez add_module() avant add_dependency()."
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
            batch = sorted(m for m, level in levels.items() if level == lvl)
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
        with open(path, encoding="utf-8") as fh:
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

    # ------------------------------------------------------------------
    # Planification LLM
    # ------------------------------------------------------------------

    @staticmethod
    def _build_planning_prompt(spec_content: str) -> str:
        """Construit le prompt de découpage modulaire pour le LLM.

        Le prompt demande au LLM d'analyser le spec et de produire
        un découpage en modules indépendants avec leurs dépendances
        et contrats d'interface.

        Args:
            spec_content: Contenu brut du fichier spec.

        Returns:
            Le prompt complet à envoyer au provider.
        """
        return (
            "Tu es un architecte logiciel expert en découpage modulaire.\n"
            "Analyse la spécification suivante et décompose-la en modules "
            "indépendants avec leurs contrats d'interface.\n\n"
            "=== SPÉCIFICATION ===\n"
            f"{spec_content}\n"
            "=== FIN SPÉCIFICATION ===\n\n"
            "Retourne UNIQUEMENT un objet JSON (pas de commentaire, pas de markdown) "
            "avec cette structure :\n"
            "{\n"
            '  "modules": [\n'
            "    {\n"
            '      "id": "identifiant_unique",\n'
            '      "name": "Nom lisible",\n'
            '      "responsibility": "Responsabilité précise du module",\n'
            '      "estimated_lines": 500\n'
            "    }\n"
            "  ],\n"
            '  "contracts": [\n'
            "    {\n"
            '      "producer": "id_producteur",\n'
            '      "consumer": "id_consommateur",\n'
            '      "interface_description": "Description de l\'interface"\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Contraintes :\n"
            "- Chaque module doit avoir estimated_lines entre 100 et 10000.\n"
            "- Les contracts doivent référencer des ids de modules existants.\n"
            "- Le graphe ne doit pas contenir de cycle.\n"
        )

    @staticmethod
    def _parse_plan_response(text: str) -> dict:
        """Extrait le JSON de la réponse LLM.

        Gère les cas où le LLM entoure le JSON de balises markdown
        (```json ... ```) ou renvoie du texte avant/après.

        Args:
            text: Réponse brute du LLM.

        Returns:
            Le dictionnaire parsé.

        Raises:
            ValueError: si aucun JSON valide n'est trouvé.
        """
        # Essai 1 : bloc de code markdown
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1))

        # Essai 2 : premier objet JSON dans le texte
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))

        raise ValueError(
            f"Impossible d'extraire un JSON de la réponse LLM. Début de la réponse : {text[:200]!r}"
        )

    @classmethod
    def from_spec(
        cls,
        spec_path: str | Path,
        provider: object,
        *,
        enrich: bool = False,
    ) -> tuple[ModuleGraph, CascadePlan, dict | None]:
        """Construit un ModuleGraph et son CascadePlan depuis un fichier spec.

        ⚠️ FROZEN SPECS SQUELETTIQUES : Les frozen specs générées automatiquement
        contiennent UN SEUL invariant (la responsabilité du module) avec
        verified=False et source="auto-from-planning". Elles sont conçues comme
        point de départ à enrichir manuellement ou via enrich=True
        (passage LLM dédié avec frozen_spec_gen.j2).

        Si enrich=True, un 2e appel LLM est effectué par module pour générer
        3–5 invariants supplémentaires (source="llm-generated", verified=False).
        Aucun invariant llm-generated ne passe en verified=True automatiquement :
        l'humain DOIT valider avant goal cascade run.

        Ne lancez PAS goal cascade run sans avoir validé et enrichi les
        invariants. Un invariant unique = protection minimale contre la
        dérive de simplification.

        Pipeline :
        1. Lecture du fichier spec.
        2. Construction du prompt de découpage (_build_planning_prompt).
        3. Appel LLM via provider.call().
        4. Parsing de la réponse (_parse_plan_response).
        5. Création du CascadePlan.
        6. Validation des contraintes (modules, dépendances, cycles).
        7. Construction du ModuleGraph avec frozen specs squelettiques.
        8. (Optionnel) Enrichissement LLM par module (prompts/frozen_spec_gen.j2).
        9. Calcul ordre topologique + batches parallèles.

        Args:
            spec_path: Chemin vers le fichier de spécification.
            provider: Provider LLM (doit avoir une méthode ``call(prompt, role, tier)``).
            enrich: Si True, effectue un 2e appel LLM par module pour générer
                des invariants llm-generated (verified=False).

        Returns:
            Tuple (ModuleGraph, CascadePlan, enrichment_stats).
            enrichment_stats est None si enrich=False, sinon un dict avec :
              - modules_enriched (int)
              - invariants_generated (int)
              - modules_failed (list[str])  # IDs des modules où l'appel a échoué

        Raises:
            ValueError: si le plan est invalide ou la réponse LLM illisible.
        """
        path = Path(spec_path)
        spec_content = path.read_text(encoding="utf-8")
        logger.info("Spec lue depuis %s (%d caractères)", path, len(spec_content))

        # 1. Prompt
        prompt = cls._build_planning_prompt(spec_content)

        # 2. Appel LLM (planification)
        response = provider.call(prompt, role="producer", tier="medium")
        logger.info("Réponse LLM reçue (%d caractères)", len(response.text))

        # 3. Parsing
        plan_data = cls._parse_plan_response(response.text)

        # 4. CascadePlan
        modules_raw = plan_data.get("modules", [])
        deps_raw = plan_data.get("contracts", [])

        modules = [ModuleSpec(**m) for m in modules_raw]
        deps = [DependencySpec(**d) for d in deps_raw]

        total_lines = sum(m.estimated_lines for m in modules)

        plan = CascadePlan(
            objective=spec_content[:200],
            modules=modules,
            dependencies=deps,
            total_estimated_lines=total_lines,
        )

        # 5. Validation des contraintes
        constraint_errors = plan.validate_constraints()
        if constraint_errors:
            raise ValueError("Plan invalide : " + "; ".join(constraint_errors))

        # 6. Construction du graphe avec frozen specs squelettiques
        graph = cls()

        for mod in plan.modules:
            # ⚠️ INVARIANT SQUELETTIQUE — un seul invariant = la responsabilité.
            # verified=False → l'humain DOIT valider avant run.
            # Enrichir manuellement ou via enrich=True.
            skeletal_invariant = Invariant(
                description=mod.responsibility,
                category="functional",
                verified=False,
                source="auto-from-planning",
            )
            frozen = FrozenSpec(
                module_name=mod.name,
                objective=mod.responsibility,
                invariants=[skeletal_invariant],
                max_lines=mod.estimated_lines,
            )
            graph.add_module(mod.id, frozen)

            # Warning explicite : ne pas lancer goal cascade run sans enrichir.
            logger.warning(
                "frozen_spec_skeletal module=%s invariants=%d "
                "source=auto-from-planning "
                "action=enrich_manually_or_use_enrich_flag",
                mod.id,
                len(frozen.invariants),
            )

        for dep in plan.dependencies:
            iface = InterfaceContract(
                contract_id=f"c-{dep.producer}-{dep.consumer}",
                producer_module=dep.producer,
                consumer_module=dep.consumer,
                output_description=dep.interface_description,
                input_description=dep.interface_description,
            )
            graph.add_dependency(dep.producer, dep.consumer, iface)

        # 7. Validation acyclicité
        graph.validate_acyclic()

        # 8. Enrichissement LLM (optionnel)
        enrichment_stats: dict | None = None
        if enrich:
            enrichment_stats = cls._enrich_frozen_specs(graph, plan, provider)

        logger.info(
            "Graphe construit : %d modules, ordre=%s",
            len(graph._specs),
            graph.topological_order(),
        )
        return graph, plan, enrichment_stats

    # ------------------------------------------------------------------
    # Enrichissement LLM des frozen specs (--enrich-frozen-specs)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_enrichment_prompt(
        module_name: str,
        responsibility: str,
        objective: str,
    ) -> str:
        """Construit le prompt d'enrichissement pour un module donné."""
        try:
            from ..prompts import PromptLoader

            # Utilise PromptLoader pour respecter la hiérarchie de surcharge
            loader = PromptLoader()
            return loader.load(
                "frozen_spec_gen",
                module_name=module_name,
                responsibility=responsibility,
                objective=objective,
            )
        except Exception:
            # Fallback inline si Jinja2 ou PromptLoader indisponible
            return (
                "Tu es un architecte logiciel rigoureux. Pour le module ci-dessous,\n"
                "propose entre 3 et 5 invariants vérifiables.\n\n"
                f"MODULE : {module_name}\n"
                f"RESPONSABILITÉ : {responsibility}\n"
                f"OBJECTIF GLOBAL : {objective}\n\n"
                "Réponds STRICTEMENT avec un objet JSON : "
                '{"invariants": [{"description": "...", "category": '
                '"functional|structural|non_negotiable", "test_hint": "..."}]}'
            )

    @staticmethod
    def _parse_enrichment_response(text: str) -> list[dict]:
        """Extrait la liste d'invariants de la réponse LLM.

        Returns:
            Liste de dicts {description, category, test_hint}.

        Raises:
            ValueError: si la réponse ne contient pas de JSON exploitable.
        """
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
        if match:
            return json.loads(match.group(1)).get("invariants", [])

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0)).get("invariants", [])

        raise ValueError("Impossible d'extraire le JSON d'invariants de la réponse LLM.")

    @classmethod
    def _enrich_frozen_specs(
        cls,
        graph: ModuleGraph,
        plan: CascadePlan,
        provider: object,
    ) -> dict:
        """Enrichit chaque frozen spec avec un 2e appel LLM dédié.

        Pour chaque module, génère 3-5 invariants (source="llm-generated",
        verified=False). En cas d'échec sur un module, conserve l'invariant
        squelettique et logue un warning.

        Returns:
            Dict avec modules_enriched, invariants_generated, modules_failed.
        """
        modules_enriched = 0
        invariants_generated = 0
        modules_failed: list[str] = []

        for mod in plan.modules:
            prompt = cls._build_enrichment_prompt(
                module_name=mod.name,
                responsibility=mod.responsibility,
                objective=plan.objective,
            )
            try:
                response = provider.call(prompt, role="producer", tier="medium")
                raw_inv = cls._parse_enrichment_response(response.text)
            except Exception as exc:
                logger.warning(
                    "frozen_spec_enrich_failed module=%s error=%s action=keep_skeletal",
                    mod.id,
                    exc,
                )
                modules_failed.append(mod.id)
                continue

            # Construit les nouveaux invariants typés
            new_invariants: list[Invariant] = []
            for inv_data in raw_inv:
                if not isinstance(inv_data, dict):
                    continue
                description = inv_data.get("description")
                if not description:
                    continue
                category = inv_data.get("category", "functional")
                if category not in ("functional", "structural", "non_negotiable"):
                    category = "functional"
                new_invariants.append(
                    Invariant(
                        description=description,
                        category=category,  # type: ignore[arg-type]
                        verified=False,
                        source="llm-generated",
                    )
                )

            if not new_invariants:
                logger.warning(
                    "frozen_spec_enrich_empty module=%s action=keep_skeletal",
                    mod.id,
                )
                modules_failed.append(mod.id)
                continue

            # Remplace la frozen spec du module par la version enrichie.
            # On GARDE l'invariant squelettique en premier pour traçabilité,
            # puis on ajoute les llm-generated derrière.
            existing = graph._specs[mod.id]
            merged = [*existing.invariants, *new_invariants]
            enriched = FrozenSpec(
                module_name=existing.module_name,
                objective=existing.objective,
                invariants=merged,
                max_lines=existing.max_lines,
            )
            graph._specs[mod.id] = enriched
            modules_enriched += 1
            invariants_generated += len(new_invariants)

            logger.info(
                "frozen_spec_enriched module=%s added_invariants=%d "
                "total_invariants=%d source=llm-generated",
                mod.id,
                len(new_invariants),
                len(merged),
            )

        return {
            "modules_enriched": modules_enriched,
            "invariants_generated": invariants_generated,
            "modules_failed": modules_failed,
        }

    def to_plan_dict(self) -> dict:
        """Exporte le graphe sous forme de dictionnaire sérialisable."""
        modules = []
        for mid in sorted(self._specs):
            modules.append(
                {
                    "module_id": mid,
                    "spec": self._specs[mid].model_dump(),
                }
            )
        contracts = []
        for src, tgt, data in sorted(self._dag.edges(data=True)):
            contracts.append(
                {
                    "producer": src,
                    "consumer": tgt,
                    "contract": data["contract"].model_dump(),
                }
            )
        return {"modules": modules, "contracts": contracts}
