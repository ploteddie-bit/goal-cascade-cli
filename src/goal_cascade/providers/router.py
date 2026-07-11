from __future__ import annotations

from collections.abc import Mapping

from .base import BaseProvider, LLMResponse


class RoleMappedProvider(BaseProvider):
    """Délègue chaque rôle de cascade au provider effectif résolu."""

    def __init__(
        self,
        providers_by_name: Mapping[str, BaseProvider],
        role_mapping: Mapping[str, str],
    ):
        self.providers_by_name = dict(providers_by_name)
        self.role_mapping = dict(role_mapping)

    @property
    def name(self) -> str:
        return "role-mapped"

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        provider_name = self.role_mapping.get(role)
        if provider_name is None:
            raise KeyError(f"Aucun provider configuré pour le rôle {role!r}")
        provider = self.providers_by_name.get(provider_name)
        if provider is None:
            raise KeyError(f"Provider effectif absent : {provider_name!r}")
        return provider.call(prompt, role=role, tier=tier)
