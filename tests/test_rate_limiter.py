"""Tests unitaires pour le rate limiter isole.

Couvre :
- backoff exponentiel exact (formule initial_backoff * multiplier^attempt)
- fallback success apres retry epuise
- ProviderExhaustedError leve quand aucun fallback disponible
- pas de fallback appele si premiere tentative reussit
- re-exports depuis mirascope_provider preservent la retro-compatibilite
- FALLBACK_CHAIN a des backends distincts du primaire
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from goal_cascade.providers.base import LLMResponse
from goal_cascade.providers.rate_limiter import (
    Backend,
    FALLBACK_CHAIN,
    ProviderExhaustedError,
    ProviderUnavailableError,
    RateLimitConfig,
    RateLimitError,
    call_with_retry_and_fallback,
)


def _make_response(text: str, backend: Backend) -> LLMResponse:
    return LLMResponse(
        text=text,
        provider=backend.value,
        model="fake-model",
        input_tokens=1,
        output_tokens=2,
        cost_usd=0.0,
    )


def _async_sync(sync_fn: Any):
    """Convertit une fonction sync en callable async pour les tests."""

    async def wrapper(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        return sync_fn(backend, prompt, role, tier)

    return wrapper


def test_fallback_chain_uses_distinct_backends() -> None:
    """Chaque backend primaire a une liste de fallback distincte de lui-meme."""
    for backend, fallbacks in FALLBACK_CHAIN.items():
        assert backend not in fallbacks, f"{backend} ne doit pas se fallback sur lui-meme"
        assert fallbacks, f"{backend} doit avoir au moins un fallback"


def test_retry_on_rate_limit_with_exponential_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le backoff exponentiel est applique entre les tentatives de retry."""
    calls: list[Backend] = []
    sleeps: list[float] = []

    async def fake_async_sleep(wait: float) -> None:
        sleeps.append(wait)

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if len(calls) < 3:
            raise RateLimitError("429")
        return _make_response("ok", backend)

    config = RateLimitConfig(max_retries=3, initial_backoff_s=0.01, backoff_multiplier=2.0)
    monkeypatch.setattr("asyncio.sleep", fake_async_sleep)

    response = asyncio.run(
        call_with_retry_and_fallback(
            backend_call=_async_sync(sync_call_backend),
            backend=Backend.ANTHROPIC,
            prompt="prompt",
            role="producer",
            tier="small",
            rate_config=config,
            available_backends={Backend.ANTHROPIC},
        )
    )

    assert response.text == "ok"
    assert calls == [Backend.ANTHROPIC, Backend.ANTHROPIC, Backend.ANTHROPIC]
    # Backoff : 0.01 * 2^0 = 0.01, puis 0.01 * 2^1 = 0.02
    assert sleeps == [0.01, 0.02]


def test_fallback_when_primary_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apres retry epuise, le fallback chain est tente."""
    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if backend == Backend.ANTHROPIC:
            raise RateLimitError("429")
        return _make_response("fallback-ok", backend)

    config = RateLimitConfig(max_retries=1, initial_backoff_s=0.001)

    response = asyncio.run(
        call_with_retry_and_fallback(
            backend_call=_async_sync(sync_call_backend),
            backend=Backend.ANTHROPIC,
            prompt="prompt",
            role="critic",
            tier="medium",
            rate_config=config,
            available_backends={Backend.ANTHROPIC, Backend.OPENAI},
        )
    )

    assert response.provider == "openai"
    assert response.text == "fallback-ok"
    assert calls == [Backend.ANTHROPIC, Backend.OPENAI]


def test_provider_unavailable_skips_retry_and_goes_to_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ProviderUnavailableError ne retry pas, va directement au fallback."""
    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if backend == Backend.ANTHROPIC:
            raise ProviderUnavailableError("down")
        return _make_response("ok", backend)

    config = RateLimitConfig(max_retries=5, initial_backoff_s=0.001)

    response = asyncio.run(
        call_with_retry_and_fallback(
            backend_call=_async_sync(sync_call_backend),
            backend=Backend.ANTHROPIC,
            prompt="p",
            role="critic",
            tier="medium",
            rate_config=config,
            available_backends={Backend.ANTHROPIC, Backend.GOOGLE},
        )
    )

    # Anthropic tente 1 fois (pas de retry sur ProviderUnavailable), puis fallback google
    assert calls == [Backend.ANTHROPIC, Backend.GOOGLE]
    assert response.provider == "google"


def test_exhausted_raises_when_all_backends_fail() -> None:
    """Aucun backend ne reussit : ProviderExhaustedError est leve."""
    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        raise ProviderUnavailableError("all-down")

    config = RateLimitConfig(max_retries=1, initial_backoff_s=0.001)

    with pytest.raises(ProviderExhaustedError, match="Tous les providers"):
        asyncio.run(
            call_with_retry_and_fallback(
                backend_call=_async_sync(sync_call_backend),
                backend=Backend.ANTHROPIC,
                prompt="p",
                role="producer",
                tier="small",
                rate_config=config,
                available_backends={Backend.ANTHROPIC},
            )
        )

    # Anthropic tente une fois, pas de fallback disponible
    assert calls == [Backend.ANTHROPIC]


def test_no_fallback_called_when_first_attempt_succeeds() -> None:
    """Si la premiere tentative reussit, aucun fallback n'est appele."""
    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        return _make_response("first-try", backend)

    config = RateLimitConfig(max_retries=3, initial_backoff_s=0.001)

    response = asyncio.run(
        call_with_retry_and_fallback(
            backend_call=_async_sync(sync_call_backend),
            backend=Backend.OPENAI,
            prompt="p",
            role="producer",
            tier="small",
            rate_config=config,
            available_backends={Backend.OPENAI, Backend.ANTHROPIC, Backend.GOOGLE},
        )
    )

    assert response.text == "first-try"
    assert calls == [Backend.OPENAI]


def test_fallback_skips_backends_not_in_available() -> None:
    """Les backends non disponibles sont ignores meme s'ils sont dans la chain."""
    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if backend == Backend.ANTHROPIC:
            raise RateLimitError("429")
        return _make_response("ok", backend)

    config = RateLimitConfig(max_retries=1, initial_backoff_s=0.001)

    # available_backends exclut OPENAI (qui est le premier fallback) et inclut GOOGLE
    response = asyncio.run(
        call_with_retry_and_fallback(
            backend_call=_async_sync(sync_call_backend),
            backend=Backend.ANTHROPIC,
            prompt="p",
            role="critic",
            tier="medium",
            rate_config=config,
            available_backends={Backend.ANTHROPIC, Backend.GOOGLE},
        )
    )

    # OPENAI est dans FALLBACK_CHAIN[ANTHROPIC] mais pas dans available_backends
    # donc on saute a GOOGLE directement
    assert response.provider == "google"
    assert calls == [Backend.ANTHROPIC, Backend.GOOGLE]


def test_fallback_skips_backends_in_same_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defense Pilier 1 : un fallback vers la meme famille est refuse.

    On patche PROVIDER_FAMILIES pour mettre anthropic et openai dans la meme
    famille, simulant un cas theorique ou deux providers distincts partagent
    en fait la meme infra. Le fallback openai doit etre skippe, et comme
    google reste dans une autre famille, on bascule vers google.
    """
    from goal_cascade.providers import rate_limiter
    from goal_cascade.providers.families import PROVIDER_FAMILIES as real_families

    fake_families = dict(real_families)
    fake_families["anthropic"] = "anthropic_openai"
    fake_families["openai"] = "anthropic_openai"
    # google reste dans sa famille d'origine
    monkeypatch.setattr(rate_limiter, "PROVIDER_FAMILIES", fake_families)

    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if backend == Backend.ANTHROPIC:
            raise RateLimitError("429")
        return _make_response("ok", backend)

    config = RateLimitConfig(max_retries=1, initial_backoff_s=0.001)

    response = asyncio.run(
        call_with_retry_and_fallback(
            backend_call=_async_sync(sync_call_backend),
            backend=Backend.ANTHROPIC,
            prompt="p",
            role="critic",
            tier="medium",
            rate_config=config,
            available_backends={Backend.ANTHROPIC, Backend.OPENAI, Backend.GOOGLE},
        )
    )

    # openai (meme famille) doit etre skippe ; bascule vers google
    assert response.provider == "google"
    assert Backend.OPENAI not in calls


def test_fallback_all_in_same_family_raises_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si TOUS les fallbacks sont dans la meme famille, ProviderExhaustedError."""
    from goal_cascade.providers import rate_limiter
    from goal_cascade.providers.families import PROVIDER_FAMILIES as real_families

    fake_families = dict(real_families)
    # Tous les backends Mirascope dans la meme famille
    fake_families["anthropic"] = "all_same"
    fake_families["openai"] = "all_same"
    fake_families["google"] = "all_same"
    monkeypatch.setattr(rate_limiter, "PROVIDER_FAMILIES", fake_families)

    calls: list[Backend] = []

    def sync_call_backend(backend: Backend, prompt: str, role: str, tier: str) -> LLMResponse:
        calls.append(backend)
        if backend == Backend.ANTHROPIC:
            raise RateLimitError("429")
        return _make_response("ok", backend)

    config = RateLimitConfig(max_retries=1, initial_backoff_s=0.001)

    with pytest.raises(ProviderExhaustedError, match="Tous les providers"):
        asyncio.run(
            call_with_retry_and_fallback(
                backend_call=_async_sync(sync_call_backend),
                backend=Backend.ANTHROPIC,
                prompt="p",
                role="producer",
                tier="small",
                rate_config=config,
                available_backends={Backend.ANTHROPIC, Backend.OPENAI, Backend.GOOGLE},
            )
        )

    # Anthropic a ete tente 1 fois, mais aucun fallback n'a ete appele
    # (tous skippes pour meme famille).
    assert calls == [Backend.ANTHROPIC]


def test_mirascope_provider_re_exports() -> None:
    """Les imports depuis mirascope_provider fonctionnent toujours (retro-compat)."""
    from goal_cascade.providers import mirascope_provider as mp

    assert mp.Backend is Backend
    assert mp.RateLimitConfig is RateLimitConfig
    assert mp.RateLimitError is RateLimitError
    assert mp.ProviderUnavailableError is ProviderUnavailableError
    assert mp.ProviderExhaustedError is ProviderExhaustedError
    assert mp.FALLBACK_CHAIN is FALLBACK_CHAIN