"""FrozenSpec — spécifications gelées des modules (spec V2 §4.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Invariant(BaseModel):
    """Un invariant vérifiable de la frozen spec (spec V2 §4.3)."""

    description: str
    category: Literal["functional", "structural", "non_negotiable"] = "functional"
    verified: bool | None = None
    source: Literal["manual", "auto-from-planning", "llm-generated"] = "manual"


class FrozenSpec(BaseModel):
    """Spécification gelée d'un module (spec V2 §4.3).

    Aucun invariant ne peut être supprimé sans validation humaine.
    Chaque module d'un multi-cascade a sa propre FrozenSpec.
    """

    module_name: str
    objective: str
    invariants: list[Invariant] = Field(..., min_length=1)
    max_lines: int = Field(default=3000, ge=100, le=10000)

    def all_verified(self) -> bool:
        return all(inv.verified for inv in self.invariants)

    def missing_invariants(self) -> list[Invariant]:
        return [inv for inv in self.invariants if not inv.verified]
