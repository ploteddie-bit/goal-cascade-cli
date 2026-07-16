"""DEPRECATED — use goal_cascade.schemas directly.

Ce module reste pour backward-compat avec les imports existants
``from goal_cascade.schemas.models import X``. Les nouveaux imports doivent
utiliser directement ``from goal_cascade.schemas import X`` (via __init__.py).

Organisation effective (cf. spec V2 §14) :
- synthesis.py    : GoalOrientedSynthesis
- frozen_spec.py  : Invariant, FrozenSpec
- interface.py    : InterfaceInvariant, InterfaceContract
- verdict.py      : Verdict
- receipt.py      : LLMCallRecord, RunReceipt
- state.py        : IterationRole, Variant, ImmutableArtifact, CascadeState
"""

from .frozen_spec import FrozenSpec, Invariant
from .interface import InterfaceContract, InterfaceInvariant
from .receipt import LLMCallRecord, RunReceipt
from .synthesis import GoalOrientedSynthesis
from .verdict import Verdict
from .state import (
    CascadeState,
    ImmutableArtifact,
    IterationRole,
    Variant,
)

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
