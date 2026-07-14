"""Tests du MirascopeProvider.

Note : les tests de retry/timeout/fallback ont demenage dans
``tests/test_rate_limiter.py`` apres l'extraction du rate limiter.
La logique de resilience est testee la-bas, directement sur la
fonction ``call_with_retry_and_fallback``.
"""

from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass

import pytest

from goal_cascade.providers.base import LLMResponse
from goal_cascade.providers.families import PROVIDER_FAMILIES
from goal_cascade.providers.mirascope_provider import (
    FALLBACK_CHAIN,
    Backend,
    MirascopeProvider,
    RateLimitConfig,
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

    assert _estimate_cost_anthropic("claude-haiku-3-5", usage) > 0
    assert _estimate_cost_openai("gpt-4o-mini", usage) > 0
    assert _estimate_cost_google("gemini-2.0-flash", usage) > 0
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
    """Chaque backend primaire a une liste de fallback distincte de lui-meme.

    Test double : la logique est aussi testee dans test_rate_limiter.py,
    ici on garde une verification rapide de l'invariant structurel.
    """
    for backend, fallbacks in FALLBACK_CHAIN.items():
        assert backend not in fallbacks
        assert fallbacks


def test_mirascope_provider_uses_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le provider delegue la resilience a call_with_retry_and_fallback.

    Verifie le contrat d'integration : quand MirascopeProvider.call est
    invoque, la logique retry+fallback est appelee avec les bons parametres.
    """
    provider = MirascopeProvider(
        Backend.ANTHROPIC,
        rate_limit_config=RateLimitConfig(max_retries=2, initial_backoff_s=0.001),
    )

    captured: dict[str, object] = {}

    async def fake_call_with_retry_and_fallback(
        backend_call: object,
        backend: Backend,
        prompt: str,
        role: str,
        tier: str,
        rate_config: RateLimitConfig,
        available_backends: object,
    ) -> LLMResponse:
        captured["backend"] = backend
        captured["prompt"] = prompt
        captured["role"] = role
        captured["tier"] = tier
        captured["rate_config"] = rate_config
        return LLMResponse(text="delegated", provider="anthropic", model="x")

    monkeypatch.setattr(
        "goal_cascade.providers.mirascope_provider.call_with_retry_and_fallback",
        fake_call_with_retry_and_fallback,
    )

    response = provider.call("hello", "producer", "small")

    assert response.text == "delegated"
    assert captured["backend"] == Backend.ANTHROPIC
    assert captured["prompt"] == "hello"
    assert captured["role"] == "producer"
    assert captured["tier"] == "small"
    assert captured["rate_config"].max_retries == 2