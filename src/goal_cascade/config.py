from __future__ import annotations

import logging
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .providers.families import PROVIDER_FAMILIES
from .providers.rate_limiter import RateLimitConfig
from .orchestrator.budget_tracker import BudgetConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".goal" / "config.toml"
MAIN_ROLES: tuple[str, ...] = ("producer", "critic", "adversary", "arbiter")
ALL_ROLES: tuple[str, ...] = (*MAIN_ROLES, "synthesizer")
MIN_OPTIMAL_PROVIDERS = 3


class ProviderAdaptation(BaseModel):
    role: str
    configured: str | None
    effective: str


class ProviderMappingRow(BaseModel):
    role: str
    configured: str | None
    effective: str
    auto_switched: bool


class ProvidersConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: list[str] = Field(..., min_length=1, description="Au moins 1 provider requis")
    role_mapping: dict[str, str] = Field(default_factory=dict)
    synthesizer: str = Field(...)
    require_diversity: bool = False
    resolved_role_mapping: dict[str, str] = Field(default_factory=dict)
    resolved_synthesizer: str = ""
    degraded: bool = False
    adaptations: list[ProviderAdaptation] = Field(default_factory=list)

    @model_validator(mode="after")
    def resolve_providers(self) -> "ProvidersConfig":
        ordered_available = list(dict.fromkeys(self.enabled))
        available = set(ordered_available)
        if not available:
            raise ValueError("Aucun provider activé dans enabled=[]")

        resolved: dict[str, str] = {}
        adaptations: list[ProviderAdaptation] = []
        previous_effective: str | None = None

        for role in MAIN_ROLES:
            configured = self.role_mapping.get(role)
            if configured in available:
                effective = configured
            else:
                effective = previous_effective or ordered_available[0]
                adaptations.append(
                    ProviderAdaptation(
                        role=role,
                        configured=configured,
                        effective=effective,
                    )
                )
                logger.warning(
                    "Provider %r indisponible pour %s. Auto-switch vers %r (mode dégradé).",
                    configured,
                    role,
                    effective,
                )
            resolved[role] = effective
            previous_effective = effective

        if self.synthesizer in available:
            resolved_synthesizer = self.synthesizer
        else:
            resolved_synthesizer = resolved.get("producer") or ordered_available[0]
            adaptations.append(
                ProviderAdaptation(
                    role="synthesizer",
                    configured=self.synthesizer,
                    effective=resolved_synthesizer,
                )
            )
            logger.warning(
                "Provider %r indisponible pour synthesizer. Auto-switch vers %r (mode dégradé).",
                self.synthesizer,
                resolved_synthesizer,
            )

        degraded = bool(adaptations) or len(available) < MIN_OPTIMAL_PROVIDERS

        families_used: dict[str, list[str]] = {}
        for role_name, provider_name in resolved.items():
            family = PROVIDER_FAMILIES.get(provider_name, provider_name)
            families_used.setdefault(family, []).append(role_name)
        synthesizer_family = PROVIDER_FAMILIES.get(resolved_synthesizer, resolved_synthesizer)
        families_used.setdefault(synthesizer_family, []).append("synthesizer")

        providers_by_family: dict[str, set[str]] = {}
        all_assigned = dict(resolved)
        all_assigned["synthesizer"] = resolved_synthesizer
        for provider_name in all_assigned.values():
            family = PROVIDER_FAMILIES.get(provider_name, provider_name)
            providers_by_family.setdefault(family, set()).add(provider_name)

        same_family = {
            family: roles
            for family, roles in families_used.items()
            if len(roles) > 1
            and family != "mock"
            and len(providers_by_family.get(family, set())) > 1
        }
        if same_family:
            degraded = True
            details = "; ".join(
                f"{family}: {', '.join(roles)}"
                for family, roles in same_family.items()
            )
            if self.require_diversity:
                raise ValueError(
                    "require_diversity=true : plusieurs rôles dans la même famille. "
                    f"{details}"
                )
            logger.warning("Diversité réduite : mêmes familles détectées. %s", details)

        if self.require_diversity and degraded:
            raise ValueError(
                "require_diversity=true interdit le mode dégradé : "
                f"{len(available)}/{MIN_OPTIMAL_PROVIDERS} provider(s) disponible(s), "
                f"adaptations={[(item.role, item.configured, item.effective) for item in adaptations]}"
            )

        if len(available) < MIN_OPTIMAL_PROVIDERS:
            logger.warning(
                "Mode dégradé : seulement %s/%s provider(s) disponible(s). Mapping effectif : %s",
                len(available),
                MIN_OPTIMAL_PROVIDERS,
                resolved,
            )

        self.resolved_role_mapping = resolved
        self.resolved_synthesizer = resolved_synthesizer
        self.degraded = degraded
        self.adaptations = adaptations
        return self

    def mapping_rows(self) -> list[ProviderMappingRow]:
        rows: list[ProviderMappingRow] = []
        for role in MAIN_ROLES:
            configured = self.role_mapping.get(role)
            effective = self.resolved_role_mapping[role]
            rows.append(
                ProviderMappingRow(
                    role=role,
                    configured=configured,
                    effective=effective,
                    auto_switched=configured != effective,
                )
            )
        rows.append(
            ProviderMappingRow(
                role="synthesizer",
                configured=self.synthesizer,
                effective=self.resolved_synthesizer,
                auto_switched=self.synthesizer != self.resolved_synthesizer,
            )
        )
        return rows


class GoalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: ProvidersConfig
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)


def load_goal_config(path: Path) -> GoalConfig:
    with path.expanduser().open("rb") as handle:
        data = tomllib.load(handle)
    return GoalConfig.model_validate(data)
