"""Schema du CascadePlan — plan de decomposition d'un objectif en modules.

Contient ModuleSpec, DependencySpec et CascadePlan avec validation
des contraintes (unicite des IDs, referentiels valides, pas de cycle).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModuleSpec(BaseModel):
    """Specification d'un module du plan de cascade."""

    id: str = Field(..., description="Identifiant unique du module")
    name: str = Field(..., description="Nom lisible du module")
    responsibility: str = Field(..., description="Responsabilite du module")
    estimated_lines: int = Field(
        ...,
        ge=100,
        le=10000,
        description="Nombre estime de lignes de code",
    )
    frozen_spec_prompt: str = Field(
        default="",
        description="Prompt pour generer la frozen spec du module",
    )


class DependencySpec(BaseModel):
    """Dependance entre deux modules (producteur -> consommateur)."""

    producer: str = Field(..., description="ID du module producteur")
    consumer: str = Field(..., description="ID du module consommateur")
    interface_description: str = Field(
        ...,
        description="Description de l'interface entre les deux modules",
    )


class CascadePlan(BaseModel):
    """Plan de decomposition d'un objectif en modules avec dependances.

    Contient la topologie (ordre topologique + lots paralleles) et
    la methode validate_constraints() pour verifier la coherence.
    """

    objective: str = Field(..., min_length=1)
    modules: list[ModuleSpec] = Field(..., min_length=1)
    dependencies: list[DependencySpec] = Field(default_factory=list)
    topological_order: list[str] = Field(default_factory=list)
    parallel_batches: list[list[str]] = Field(default_factory=list)
    total_estimated_lines: int = Field(default=0)

    def validate_constraints(self) -> list[str]:
        """Verifie les contraintes du plan et retourne les erreurs.

        Contraintes verifiees :
        - total_estimated_lines < 3000
        - IDs de modules uniques
        - Les dependances referentient des modules valides
        - Pas de dependance circulaire

        Returns:
            Liste de messages d'erreur (vide si tout est OK).
        """
        errors: list[str] = []
        module_ids = {m.id for m in self.modules}

        # 1. Contrainte de taille totale
        if self.total_estimated_lines >= 3000:
            errors.append(f"total_estimated_lines ({self.total_estimated_lines}) >= 3000")

        # 2. Unicite des IDs
        seen_ids: set[str] = set()
        for m in self.modules:
            if m.id in seen_ids:
                errors.append(f"ID de module duplique : {m.id}")
            seen_ids.add(m.id)

        # 3. Validite referentielle des dependances
        for dep in self.dependencies:
            if dep.producer not in module_ids:
                errors.append(f"Dependance : producteur inconnu '{dep.producer}'")
            if dep.consumer not in module_ids:
                errors.append(f"Dependance : consommateur inconnu '{dep.consumer}'")

        # 4. Detection de cycle (Kahn's algorithm)
        if self.dependencies and not errors:
            cycle = self._detect_cycle(module_ids)
            if cycle:
                errors.append(f"Dependance circulaire detectee : {' -> '.join(cycle)}")

        return errors

    def _detect_cycle(self, module_ids: set[str]) -> list[str] | None:
        """Detecte un cycle dans le graphe de dependances via Kahn.

        Returns:
            Le chemin du cycle s'il existe, None sinon.
        """
        # Construire le graphe d'adjacence
        adj: dict[str, list[str]] = {mid: [] for mid in module_ids}
        in_degree: dict[str, int] = dict.fromkeys(module_ids, 0)

        for dep in self.dependencies:
            adj[dep.producer].append(dep.consumer)
            in_degree[dep.consumer] += 1

        # Kahn : retirer les noeuds sans predecesseur
        queue = [n for n in module_ids if in_degree[n] == 0]
        visited = 0

        while queue:
            node = queue.pop(0)
            visited += 1
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited == len(module_ids):
            return None  # Pas de cycle

        # Retrouver le cycle pour le message d'erreur
        remaining = {n for n in module_ids if in_degree[n] > 0}
        if not remaining:
            return None

        start = next(iter(remaining))
        path = [start]
        current = start
        while True:
            next_node = None
            for neighbor in adj[current]:
                if neighbor in remaining:
                    next_node = neighbor
                    break
            if next_node is None:
                break
            if next_node in path:
                cycle_start = path.index(next_node)
                return path[cycle_start:] + [next_node]
            path.append(next_node)
            current = next_node

        return path if remaining else None
