"""Schemas Pydantic pour le versionnement des runs Cascade.

Permet de tracer les versions d'un run, comparer deux versions (diff),
et lister toutes les versions d'un run triees par date.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunVersion(BaseModel):
    """Version individuelle d'un run Cascade."""

    version_id: str
    run_id: str
    parent_version: str | None = None
    created_at: str = Field(
        ...,
        description="Horodatage ISO 8601 de creation de la version",
    )
    iteration_count: int = Field(..., ge=0, le=5)
    final_verdict: str = Field(
        ...,
        description="Verdict final (STOP, CONTINUE, forced_stop, budget_exceeded)",
    )
    total_cost_usd: float = Field(..., ge=0)
    status: str = Field(..., description="Statut du run (running, stopped, failed, etc.)")
    objective: str
    variant: str = Field(default="A", description="Variante du livrable")
    tags: list[str] = Field(default_factory=list)


class VersionDiff(BaseModel):
    """Comparaison entre deux versions d'un meme run."""

    run_id: str
    version_a: str
    version_b: str
    cost_delta_usd: float = Field(
        ...,
        description="Delta de cout entre version_a et version_b",
    )
    iteration_delta: int = Field(
        ...,
        description="Difference du nombre d'iterations",
    )
    verdict_changed: bool
    verdict_a: str
    verdict_b: str
    new_artifacts: int = Field(..., ge=0)
    removed_artifacts: int = Field(..., ge=0)
    summary: str = Field(
        ...,
        description="Resume textuel des differences",
    )


class RunVersionsList(BaseModel):
    """Liste des versions d'un run, triee par date de creation."""

    run_id: str
    versions: list[RunVersion] = Field(default_factory=list)
    latest_version: str | None = None
    total_versions: int = Field(..., ge=0)

    @classmethod
    def from_versions(cls, run_id: str, versions: list[RunVersion]) -> RunVersionsList:
        """Construit la liste triee par created_at (ordre croissant).

        Definit latest_version comme le dernier element apres tri.
        """
        sorted_versions = sorted(versions, key=lambda v: v.created_at)
        latest = sorted_versions[-1].version_id if sorted_versions else None
        return cls(
            run_id=run_id,
            versions=sorted_versions,
            latest_version=latest,
            total_versions=len(sorted_versions),
        )
