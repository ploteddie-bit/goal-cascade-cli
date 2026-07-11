"""Schemas Pydantic — le typage du framework G.O.A.L. Cascade.

Chaque concept du framework devient un modele Pydantic valide.
Voir framework-multi-agents.md, section 4 pour les details.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    objective: str = Field(
        ..., min_length=1,
        description="Objectif initial, reformule en une phrase (non vide)",
    )
    key_decisions: list[str] = Field(
        ..., min_length=1, max_length=5,
        description="3 a 5 decisions cles maximum"
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Points non tranches ou a verifier"
    )
    next_instruction: str = Field(
        ..., min_length=1,
        description="Role de l'iteration suivante + ce qu'elle doit produire (non vide)",
    )
    iteration_from: int
    iteration_to: int

    @field_validator("objective", "next_instruction", mode="before")
    @classmethod
    def _strip_whitespace(cls, v: str) -> str:
        if isinstance(v, str):
            v = v.strip()
        return v


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
    provider: str = Field(..., description="Provider utilisé (anthropic, openai, google, mock)")
    model: str = Field(..., description="Modèle concret (ex: claude-haiku-4-5)")
    iteration: int = Field(..., ge=1, le=5)
    role: str = Field(..., description="Rôle dans la cascade (producer, critic, adversary, arbiter, synthesizer)")
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: int = Field(default=0, ge=0)
    raw_output: str = ""
    token_count_estimated: bool = False
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    timestamp_utc: str = Field(
        default="",
        description="Horodatage ISO 8601 UTC de l'appel (vide si non mesuré)",
    )


class RunReceipt(BaseModel):
    """Recu detaille d'un run complet (transparence radicale des couts).

    Voir la section 9 du plan d'implementation v2. La construction se fait
    via ``RunReceipt.from_calls()`` (classmethod) ou manuellement.
    """
    run_id: str
    objective: str
    total_iterations: int = Field(..., ge=0, le=5)
    final_verdict: str = Field(..., description="STOP, CONTINUE, forced_stop, budget_exceeded")
    total_duration_s: float = Field(..., ge=0.0)
    calls: list[LLMCallRecord] = Field(default_factory=list)
    total_cost_usd: float = Field(..., ge=0.0)
    cache_hit_rate: float = Field(
        ..., ge=0.0, le=1.0,
        description="cache_read_tokens / total_input_tokens"
    )
    projected_monthly_cost: float = Field(
        ..., ge=0.0,
        description="Basé sur runs_per_day_projection × 30 jours"
    )

    @classmethod
    def from_calls(
        cls,
        run_id: str,
        objective: str,
        verdict: str,
        duration_s: float,
        calls: list[LLMCallRecord],
        runs_per_day: int = 10,
    ) -> RunReceipt:
        """Construit un RunReceipt à partir d'une liste d'appels.

        Calcule automatiquement total_cost, cache_hit_rate et
        projected_monthly_cost. Plus DRY que de calculer côté appelant.
        """
        total_cost = sum(c.cost_usd for c in calls)
        total_input = sum(c.input_tokens for c in calls)
        total_cache_read = sum(c.cache_read_tokens for c in calls)
        cache_rate = total_cache_read / total_input if total_input > 0 else 0.0
        projected = total_cost * runs_per_day * 30

        return cls(
            run_id=run_id,
            objective=objective,
            total_iterations=max((c.iteration for c in calls), default=0),
            final_verdict=verdict,
            total_duration_s=duration_s,
            calls=calls,
            total_cost_usd=total_cost,
            cache_hit_rate=cache_rate,
            projected_monthly_cost=projected,
        )

    def summary_lines(self) -> list[str]:
        """Retourne les lignes du résumé pour affichage CLI.

        Découple le schema de la présentation rich. Le formatage rich
        est fait dans cli.py ; ce méthode fournit les données structurées.
        """
        lines = [
            f" Itérations : {self.total_iterations}/5    Verdict : {self.final_verdict}",
            f" Durée : {self.total_duration_s:.1f}s      Coût total : ${self.total_cost_usd:.4f}",
            "",
            f" {'ÉTAPE':<16} {'PROVIDER':<12} {'IN':>6} {'OUT':>6} {'CACHE':>6} {'COÛT':>8}",
            " " + "-" * 60,
        ]
        for call in self.calls:
            cost_str = f"${call.cost_usd:.4f}" if call.cost_usd > 0 else "free"
            lines.append(
                f" {call.role:<16} {call.provider:<12} {call.input_tokens:>6} "
                f"{call.output_tokens:>6} {call.cache_read_tokens:>6} "
                f"{cost_str:>8}"
            )
        lines.append(" " + "-" * 60)
        total_in = sum(c.input_tokens for c in self.calls)
        total_out = sum(c.output_tokens for c in self.calls)
        total_cache = sum(c.cache_read_tokens for c in self.calls)
        lines.append(
            f" {'TOTAL':<16} {'':<12} {total_in:>6} {total_out:>6} "
            f"{total_cache:>6} ${self.total_cost_usd:>7.4f}"
        )
        lines.append("")
        lines.append(f"  Cache hit rate : {self.cache_hit_rate:.0%}")
        lines.append(f"  Projeté ({10} runs/jour) : ~${self.projected_monthly_cost:.2f}/mois")
        return lines


class Verdict(BaseModel):
    """Verdict de l'iteration 4 (Arbitre)."""
    model_config = ConfigDict(extra="forbid")

    decision: Literal["STOP", "CONTINUE"]
    justification: str


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
    status: Literal["running", "stopped", "forced_stop", "budget_exceeded", "failed"] = "running"
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
