from __future__ import annotations

import pytest

from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.providers.router import RoleMappedProvider


class NamedProvider(BaseProvider):
    def __init__(self, name: str):
        self._name = name
        self.calls: list[tuple[str, str, str]] = []

    @property
    def name(self) -> str:
        return self._name

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        self.calls.append((prompt, role, tier))
        return LLMResponse(
            text=f"{self._name}:{role}:{tier}", provider=self._name, model=f"{self._name}-{tier}"
        )


def test_role_mapped_provider_delegates_by_role() -> None:
    producer_provider = NamedProvider("producer-provider")
    critic_provider = NamedProvider("critic-provider")
    router = RoleMappedProvider(
        providers_by_name={
            "producer-provider": producer_provider,
            "critic-provider": critic_provider,
        },
        role_mapping={
            "producer": "producer-provider",
            "critic": "critic-provider",
        },
    )

    producer_response = router.call("draft", role="producer", tier="small")
    critic_response = router.call("review", role="critic", tier="medium")

    assert producer_response.provider == "producer-provider"
    assert producer_response.model == "producer-provider-small"
    assert critic_response.provider == "critic-provider"
    assert critic_response.model == "critic-provider-medium"
    assert producer_provider.calls == [("draft", "producer", "small")]
    assert critic_provider.calls == [("review", "critic", "medium")]


def test_role_mapped_provider_rejects_unmapped_role() -> None:
    router = RoleMappedProvider(
        providers_by_name={"mock": NamedProvider("mock")},
        role_mapping={"producer": "mock"},
    )

    with pytest.raises(KeyError, match="critic"):
        router.call("review", role="critic", tier="medium")


def test_role_mapped_provider_rejects_missing_provider_instance() -> None:
    router = RoleMappedProvider(
        providers_by_name={},
        role_mapping={"producer": "missing"},
    )

    with pytest.raises(KeyError, match="missing"):
        router.call("draft", role="producer", tier="small")
