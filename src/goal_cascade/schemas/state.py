"""State — CascadeState + types de base (IterationRole, Variant, ImmutableArtifact)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from .receipt import LLMCallRecord
from .synthesis import GoalOrientedSynthesis
from .verdict import Verdict
from .frozen_spec import FrozenSpec
from .interface import InterfaceContract


class IterationRole(str, Enum):
    """Les 4 rôles d'itération de la cascade."""

    PRODUCER = "producer"
    CRITIC = "critic"
    ADVERSARY = "adversary"
    ARBITER = "arbiter"


class Variant(str, Enum):
    """Variante de livrable."""

    A = "A"  # rédactionnel (article, post, rapport)
    B = "B"  # technique (code, architecture, revue)


class ImmutableArtifact(BaseModel):
    """Charge utile immuable transmise intacte entre les jonctions.
    Ne JAMAIS être synthétisée — la forme EST le signal.
    (Identifié par revue externe Qwen, section 4.3 du framework)"""

    artifact_type: Literal["code", "json_schema", "formula", "test", "config", "sql"]
    language: str | None = None
    content: str = Field(..., description="Le contenu brut, non modifié")
    checksum: str = Field(default="", description="Hash SHA-256 du contenu")
    source_iteration: int


class CascadeState(BaseModel):
    """État persistant d'une cascade en cours d'exécution."""

    run_id: str
    objective: str
    variant: Variant = Variant.A
    current_iteration: int = 0
    max_iterations: int = Field(default=5, le=5)
    history: list[LLMCallRecord] = Field(default_factory=list)
    last_synthesis: GoalOrientedSynthesis | None = None
    artifacts: list[ImmutableArtifact] = Field(default_factory=list)
    final_verdict: Verdict | None = None
    status: Literal["running", "stopped", "forced_stop", "budget_exceeded", "failed"] = "running"
    last_error: str | None = None
    accumulated_cost: float = 0.0
    last_raw_output: str = ""  # Sortie brute de la dernière itération (pour le graphe LangGraph)
    # Champs multi-cascade (S6) — optionnels, pas utilisés en cascade unique
    frozen_spec: FrozenSpec | None = None
    interface_contracts: list[InterfaceContract] = Field(default_factory=list)

    def role_for_iteration(self, n: int) -> IterationRole:
        """Retourne le rôle pour une itération donnée (1-4)."""
        roles = {
            1: IterationRole.PRODUCER,
            2: IterationRole.CRITIC,
            3: IterationRole.ADVERSARY,
            4: IterationRole.ARBITER,
        }
        if n in roles:
            return roles[n]
        # Au-delà de 4 (rebouclage), on retourne au critique
        return IterationRole.CRITIC
