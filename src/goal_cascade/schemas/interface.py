"""InterfaceContract — contrats d'interface entre modules (spec V2 §4.4)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InterfaceInvariant(BaseModel):
    """Invariant d'interface entre deux modules (spec V2 §4.4)."""

    description: str
    respected: bool | None = None


class InterfaceContract(BaseModel):
    """Contrat d'interface entre deux modules (spec V2 §4.4).

    Créé AVANT les cascades. Définit ce que le producteur fournit
    et ce que le consommateur attend.
    """

    contract_id: str
    producer_module: str
    consumer_module: str
    output_description: str
    input_description: str
    exchange_format: str = "JSON Schema"
    invariants: list[InterfaceInvariant] = Field(default_factory=list)
    error_cases: list[str] = Field(default_factory=list)
