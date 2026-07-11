"""Schemas Pydantic — le typage du framework G.O.A.L. Cascade.

Chaque concept du framework devient un modele Pydantic valide.
Voir framework-multi-agents.md, section 4 pour les details.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class IterationRole(str, Enum):
    """Les 4 roles d'iteration de la cascade."""
    PRODUCER = "producer"
    CRITIC = "critic"
    ADVERSARY = "adversary"
    ARBITER = "arbiter"


class Variant(str, Enum):
    """Variante de livrable."""
    A = "A"  # redactionnel (article, post, rapport)
    B = "B"  # technique (code, architecture, revue)


class GoalOrientedSynthesis(BaseModel):
    """Synthese transmise entre les iterations (section 4 du framework).
    Filtre le bruit, garde le signal, casse l'ancrage."""
    objective: str = Field(..., description="Objectif initial, reformule en une phrase")
    key_decisions: list[str] = Field(
        ..., min_length=1, max_length=5,
        description="3 a 5 decisions cles maximum"
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Points non tranches ou a verifier"
    )
    next_instruction: str = Field(
        ..., description="Role de l'iteration suivante + ce qu'elle doit produire"
    )
    iteration_from: int
    iteration_to: int


class ImmutableArtifact(BaseModel):
    """Charge utile immuable transmise intacte entre les jonctions.
    Ne JAMAIS etre synthetisee -- la forme EST le signal.
    (Identifie par revue externe Qwen, section 4.3 du framework)"""
    artifact_type: Literal["code", "json_schema", "formula", "test", "config", "sql"]
    language: str | None = None
    content: str = Field(..., description="Le contenu brut, non modifie")
    checksum: str = Field(default="", description="Hash SHA-256 du contenu")
    source_iteration: int


class LLMCallRecord(BaseModel):
    """Enregistrement d'un appel LLM pour la transparence des couts."""
    provider: str
    model: str
    iteration: int
    role: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    raw_output: str = ""
    token_count_estimated: bool = False


class Verdict(BaseModel):
    """Verdict de l'iteration 4 (Arbitre)."""
    decision: Literal["STOP", "CONTINUE"]
    justification: str
    alignment_ok: bool = True
    sources_verified: bool = True
    blindspots_covered: bool = True


class CascadeState(BaseModel):
    """Etat persistant d'une cascade en cours d'execution."""
    run_id: str
    objective: str
    variant: Variant = Variant.A
    current_iteration: int = 0
    max_iterations: int = Field(default=5, le=5)
    history: list[LLMCallRecord] = Field(default_factory=list)
    last_synthesis: GoalOrientedSynthesis | None = None
    artifacts: list[ImmutableArtifact] = Field(default_factory=list)
    final_verdict: Verdict | None = None
    status: Literal["running", "stopped", "forced_stop", "failed"] = "running"
    last_error: str | None = None
    accumulated_cost: float = 0.0

    def role_for_iteration(self, n: int) -> IterationRole:
        """Retourne le role pour une iteration donnee (1-4)."""
        roles = {
            1: IterationRole.PRODUCER,
            2: IterationRole.CRITIC,
            3: IterationRole.ADVERSARY,
            4: IterationRole.ARBITER,
        }
        if n in roles:
            return roles[n]
        # Au-dela de 4 (rebouclage), on retourne au critique
        return IterationRole.CRITIC
