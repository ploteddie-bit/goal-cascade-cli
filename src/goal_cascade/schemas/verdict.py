"""Verdict — décision de l'arbitre (spec V2 §4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Verdict(BaseModel):
    """Verdict de l'itération 4 (Arbitre)."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["STOP", "CONTINUE"]
    justification: str
