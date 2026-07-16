"""Synthesis — GoalOrientedSynthesis (spec V2 §4).

La synthèse orientée objectif est le mécanisme central d'anti-dérive :
elle filtre le bruit entre les itérations et casse l'ancrage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class GoalOrientedSynthesis(BaseModel):
    """Synthèse transmise entre les itérations (section 4 du framework).
    Filtre le bruit, garde le signal, casse l'ancrage."""

    objective: str = Field(
        ...,
        min_length=1,
        description="Objectif initial, reformulé en une phrase (non vide)",
    )
    key_decisions: list[str] = Field(
        ..., min_length=1, max_length=5, description="3 à 5 décisions clés maximum"
    )
    uncertainties: list[str] = Field(
        default_factory=list, description="Points non tranchés ou à vérifier"
    )
    next_instruction: str = Field(
        ...,
        min_length=1,
        description="Rôle de l'itération suivante + ce qu'elle doit produire (non vide)",
    )
    iteration_from: int
    iteration_to: int

    @field_validator("objective", "next_instruction", mode="before")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v
