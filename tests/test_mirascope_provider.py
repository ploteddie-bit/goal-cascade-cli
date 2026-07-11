from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass
from typing import Any

import pytest

from goal_cascade.providers.base import LLMResponse
from goal_cascade.providers.families import PROVIDER_FAMILIES
from goal_cascade.providers.mirascope_provider import (
    FALLBACK_CHAIN,
    Backend,
    MirascopeProvider,
    ProviderExhaustedError,
    ProviderUnavailableError,
    RateLimitConfig,
    RateLimitError,
    TIER_MODEL_MAP,
    _estimate_cost_anthropic,
    _estimate_cost_google,
    _estimate_cost_openai,
)


def test_provider_families_cover_builtin_and_mirascope_providers() -> None:
    assert PROVIDER_FAMILIES == {
        "anthropic": "anthropic",
        "openai": "openai",
        "google": "google",
        "kimi-cli": "moonshot",
        "kimi-code": "moonshot",
        "mock": "mock",
    }


def test_real_provider_families_are_distinct() -> None:
    real_providers = ["anthropic", "openai", "google"]
    families = [PROVIDER_FAMILIES[provider] for provider in real_providers]

    assert len(families) == len(set(families))


def test_package_imports_without_llm_extras() -> None:
    module = importlib.import_module("goal_cascade.providers.mirascope_provider")

    assert hasattr(module, "MirascopeProvider")


def test_tier_model_map_covers_all_backends_and_tiers() -> None:
    tiers = ["small", "medium", "large", "xlarge"]
    for backend in Backend:
        for tier in tiers:
            assert tier in TIER_MODEL_MAP[backend]
            assert TIER_MODEL_MAP[backend][tier]


def test_unknown_tier_is_rejected() -> None:
    provider = MirascopeProvider(Backend.ANTHROPIC)

    with pytest.raises(ValueError, match="Tier inconnu"):
        provider._model_for_tier(Backend.ANTHROPIC, "tiny")


@dataclass
class FakeUsage:
    input_tokens: int = 10
    output_tokens: int = 20
    prompt_tokens: int = 30
    completion_tokens: int = 40
    prompt_token_count: int = 50
    candidates_token_count: int = 60


def test_cost_estimation_uses_known_prices() -> None:
    usage = FakeUsage()

    assert _estimate_cost_anthropic("claude-haiku-4-5", usage) > 0
    assert _estimate_cost_openai("gpt-4o-mini", usage) > 0
    assert _estimate_cost_google("gemini-3-flash-preview", usage) > 0
    assert _estimate_cost_anthropic("unknown", usage) == 0


def test_call_backend_delegates_to_backend_method(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MirascopeProvider(Backend.ANTHROPIC)

    async def fake_call(prompt: str, model: str) -> LLMResponse:
        return LLMResponse(
            text=f"{model}:{prompt}",
            provider="anthropic",
            model=model,
            input_tokens=1,
            output_tokens=2,
            cost_usd=0.01,
        )

    monkeypatch.setattr(provider, "_call_anthropic", fake_call)

    response = asyncio.run(
        provider._call_backend(Backend.ANTHROPIC, "hello", "producer", "small")
    )

    assert response.text.startswith("claude-haiku")
    assert response.provider == "anthropic"
    assert response.model == TIER_MODEL_MAP[Backend.ANTHROPIC]["small"]


def test_fallback_chain_uses_distinct_backends() -> None:
    for backend, fallbacks in FALLBACK_CHAIN.items():
        assert backend not in fallbacks
        assert fallbacks


def test_retry_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MirascopeProvider(
        Backend.ANTHROPIC,
        rate_limit_config=RateLimitConfig(max_retries=3, initial_backoff_s=0.01),
        available_backends={Backend.ANTHROPIC},
    )
    calls: list[Backend] = []
    sleeps: list[float] = []

    def fake_sleep(wait: float) -> None:
        sleeps.append(wait)

    async def fake_async_sleep(wait: float) -> None:
        sleeps.append(wait)

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if len(calls) < 3:
            raise RateLimitError("429")
        return LLMResponse(text="ok", provider=backend.value, model="model")

    async def fake_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        return sync_call_backend(backend, prompt, role, tier)

    monkeypatch.setattr("asyncio.sleep", fake_async_sleep)
    monkeypatch.setattr(provider, "_call_backend", fake_call_backend)

    response = asyncio.run(provider._call_with_retry("prompt", "producer", "small"))

    assert response.text == "ok"
    assert calls == [Backend.ANTHROPIC, Backend.ANTHROPIC, Backend.ANTHROPIC]
    assert sleeps == [0.01, 0.02]


def test_fallback_when_primary_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MirascopeProvider(
        Backend.ANTHROPIC,
        rate_limit_config=RateLimitConfig(max_retries=1, initial_backoff_s=0.01),
        available_backends={Backend.ANTHROPIC, Backend.OPENAI},
    )
    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if backend == Backend.ANTHROPIC:
            raise RateLimitError("429")
        return LLMResponse(text="fallback", provider=backend.value, model="fallback-model")

    async def fake_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        return sync_call_backend(backend, prompt, role, tier)

    monkeypatch.setattr(provider, "_call_backend", fake_call_backend)

    response = asyncio.run(provider._call_with_retry("prompt", "critic", "medium"))

    assert response.provider == "openai"
    assert response.text == "fallback"
    assert calls == [Backend.ANTHROPIC, Backend.OPENAI]


def test_exhausted_raises_when_all_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MirascopeProvider(
        Backend.ANTHROPIC,
        rate_limit_config=RateLimitConfig(max_retries=1, initial_backoff_s=0.01),
        available_backends={Backend.ANTHROPIC},
    )

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        raise ProviderUnavailableError("down")

    async def fake_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        return sync_call_backend(backend, prompt, role, tier)

    monkeypatch.setattr(provider, "_call_backend", fake_call_backend)

    with pytest.raises(ProviderExhaustedError, match="Tous les providers"):
        asyncio.run(provider._call_with_retry("prompt", "producer", "small"))
