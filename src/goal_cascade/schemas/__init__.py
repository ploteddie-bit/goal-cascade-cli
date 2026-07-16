"""Schémas Pydantic — typage du framework G.O.A.L. Cascade.

Chaque concept du framework est un modèle Pydantic validé.
Voir framework-multi-agents.md, section 4 pour les détails.

Organisation (spec V2 §14) :
- synthesis.py    : GoalOrientedSynthesis
- frozen_spec.py  : Invariant, FrozenSpec
- interface.py    : InterfaceInvariant, InterfaceContract
- verdict.py      : Verdict
- receipt.py      : LLMCallRecord, RunReceipt
- state.py        : IterationRole, Variant, ImmutableArtifact, CascadeState
- plan.py         : (déjà séparé) ModuleSpec, DependencySpec, CascadePlan
- versioning.py   : (déjà séparé) RunVersion, VersionDiff
- models.py       : re-export de tout (backward-compat)
"""

from .frozen_spec import FrozenSpec, Invariant
from .interface import InterfaceContract, InterfaceInvariant
from .receipt import LLMCallRecord, RunReceipt
from .state import (
    CascadeState,
    ImmutableArtifact,
    IterationRole,
    Variant,
)
from .synthesis import GoalOrientedSynthesis
from .verdict import Verdict

__all__ = [
    "CascadeState",
    "FrozenSpec",
    "GoalOrientedSynthesis",
    "ImmutableArtifact",
    "InterfaceContract",
    "InterfaceInvariant",
    "Invariant",
    "IterationRole",
    "LLMCallRecord",
    "RunReceipt",
    "Variant",
    "Verdict",
]
