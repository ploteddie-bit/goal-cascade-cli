"""Provider multi-backend via Mirascope.

Les imports Mirascope sont paresseux pour préserver le mode local sans extra llm.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from .base import BaseProvider, LLMResponse
from .anthropic_cache import is_anthropic_sdk_available
from .rate_limiter import (
    Backend,
    FALLBACK_CHAIN,
    ProviderExhaustedError,
    ProviderUnavailableError,
    RateLimitConfig,
    RateLimitError,
    call_with_retry_and_fallback,
)

# Re-exports preserves pour retro-compatibilite avec cli.py et les tests.
# Voir providers/rate_limiter.py pour les implementations reelles.
__all__ = [
    "Backend",
    "FALLBACK_CHAIN",
    "MirascopeProvider",
    "ProviderExhaustedError",
    "ProviderUnavailableError",
    "RateLimitConfig",
    "RateLimitError",
    "TIER_MODEL_MAP",
]

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)
    logger.warning(
        "structlog non installé. Logs dégradés. Installez avec: pip install goal-cascade[llm]"
    )


TIER_MODEL_MAP: dict[Backend, dict[str, str]] = {
    Backend.ANTHROPIC: {
        "small": "claude-haiku-3-5",
        "medium": "claude-sonnet-4",
        "large": "claude-opus-4",
        "xlarge": "claude-opus-4",
    },
    Backend.OPENAI: {
        "small": "gpt-4o-mini",
        "medium": "gpt-4o",
        "large": "gpt-4o",
        "xlarge": "gpt-4o",
    },
    Backend.GOOGLE: {
        "small": "gemini-2.0-flash",
        "medium": "gemini-2.5-pro",
        "large": "gemini-2.5-pro",
        "xlarge": "gemini-2.5-pro",
    },
}


def _missing_llm_extra_message() -> str:
    return (
        "mirascope requis pour les providers réels. Installez avec: pip install goal-cascade[llm]"
    )


def _get_mirascope_module() -> Any:
    try:
        from mirascope import llm
    except ImportError as exc:
        raise ImportError(_missing_llm_extra_message()) from exc
    return llm


_MIRASCOPE_LLM: Any | None = None


def _get_llm() -> Any:
    global _MIRASCOPE_LLM
    if _MIRASCOPE_LLM is None:
        _MIRASCOPE_LLM = _get_mirascope_module()
    return _MIRASCOPE_LLM


_MIRASCOPE_EXCEPTIONS: Any | None = None


def _get_mirascope_exceptions() -> Any:
    global _MIRASCOPE_EXCEPTIONS
    if _MIRASCOPE_EXCEPTIONS is None:
        try:
            from mirascope import llm as _llm_mod
        except ImportError as exc:
            raise ImportError(_missing_llm_extra_message()) from exc
        _MIRASCOPE_EXCEPTIONS = _llm_mod.exceptions
    return _MIRASCOPE_EXCEPTIONS


_BACKEND_TO_PROVIDER: dict[Backend, str] = {
    Backend.ANTHROPIC: "anthropic",
    Backend.OPENAI: "openai",
    Backend.GOOGLE: "google",
}


def _build_model_id(backend: Backend, model: str) -> str:
    return f"{_BACKEND_TO_PROVIDER[backend]}/{model}"


def _extract_mirascope_text(response: Any) -> str:
    """Extrait le texte brut d'une réponse Mirascope v2.

    Mirascope v2 retourne ``response.content`` comme une liste d'objets ``Text``.
    ``str(response.content)`` retourne la représentation Python de la liste,
    ce qui casse le parsing JSON en aval. Cette fonction concatène les
    attributs ``.text`` de chaque bloc de contenu.
    """
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                part = getattr(item, "text", None)
                if isinstance(part, str):
                    parts.append(part)
        if parts:
            return "".join(parts)
    # Dernier recours : tomber sur la représentation str native.
    text = str(response)
    logger.warning(
        "_extract_mirascope_text: format de réponse inattendu, "
        "fallback vers str(response). Type content=%s",
        type(content).__name__,
    )
    return text


# Prix par million de tokens (input/output) — dernière vérification : 2026-07-11
ANTHROPIC_PRICES = {
    "claude-haiku-3-5": (0.80 / 1_000_000, 4.00 / 1_000_000),
    "claude-sonnet-4": (3.00 / 1_000_000, 15.00 / 1_000_000),
    "claude-opus-4": (15.00 / 1_000_000, 75.00 / 1_000_000),
}
OPENAI_PRICES = {
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gpt-4o": (2.50 / 1_000_000, 10.00 / 1_000_000),
}
GOOGLE_PRICES = {
    "gemini-2.0-flash": (0.10 / 1_000_000, 0.40 / 1_000_000),
    "gemini-2.5-pro": (1.25 / 1_000_000, 10.00 / 1_000_000),
}


def _estimate_cost_anthropic(model: str, usage: Any) -> float:
    input_price, output_price = ANTHROPIC_PRICES.get(model, (0.0, 0.0))
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    return input_tokens * input_price + output_tokens * output_price


def _estimate_cost_openai(model: str, usage: Any) -> float:
    if usage is None:
        return 0.0
    input_price, output_price = OPENAI_PRICES.get(model, (0.0, 0.0))
    input_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_tokens", 0) or 0
    output_tokens = (
        getattr(usage, "output_tokens", 0) or getattr(usage, "completion_tokens", 0) or 0
    )
    return input_tokens * input_price + output_tokens * output_price


def _estimate_cost_google(model: str, usage: Any) -> float:
    input_price, output_price = GOOGLE_PRICES.get(model, (0.0, 0.0))
    input_tokens = getattr(usage, "input_tokens", 0) or getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = (
        getattr(usage, "output_tokens", 0) or getattr(usage, "candidates_token_count", 0) or 0
    )
    return input_tokens * input_price + output_tokens * output_price


class MirascopeProvider(BaseProvider):
    def __init__(
        self,
        backend: Backend,
        rate_limit_config: RateLimitConfig | None = None,
        enable_cache: bool = True,
        available_backends: set[Backend] | None = None,
    ):
        self._backend = backend
        self._rate_config = rate_limit_config or RateLimitConfig()
        self._enable_cache = enable_cache
        self._available_backends = available_backends or set(Backend)

    @property
    def name(self) -> str:
        return self._backend.value

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                call_with_retry_and_fallback(
                    backend_call=self._call_backend,
                    backend=self._backend,
                    prompt=prompt,
                    role=role,
                    tier=tier,
                    rate_config=self._rate_config,
                    available_backends=self._available_backends,
                )
            )
        raise RuntimeError(
            "MirascopeProvider.call() ne peut pas être appelé depuis une boucle async active"
        )

    def _model_for_tier(self, backend: Backend, tier: str) -> str:
        model = TIER_MODEL_MAP[backend].get(tier)
        if model is None:
            raise ValueError(
                f"Tier inconnu '{tier}' pour backend {backend.value}. "
                f"Tiers disponibles : {list(TIER_MODEL_MAP[backend].keys())}"
            )
        return model

    async def _call_backend(
        self,
        backend: Backend,
        prompt: str,
        role: str,
        tier: str,
    ) -> LLMResponse:
        model = self._model_for_tier(backend, tier)
        started = time.monotonic()
        if backend == Backend.ANTHROPIC:
            response = await self._call_anthropic(prompt, model)
        elif backend == Backend.OPENAI:
            response = await self._call_openai(prompt, model)
        elif backend == Backend.GOOGLE:
            response = await self._call_google(prompt, model)
        else:
            raise ValueError(f"Backend non supporté : {backend}")
        response.latency_ms = int((time.monotonic() - started) * 1000)
        return response

    async def _call_anthropic(self, prompt: str, model: str) -> LLMResponse:
        return await self._call_mirascope_v2(Backend.ANTHROPIC, prompt, model)

    async def _call_openai(self, prompt: str, prompt_model: str) -> LLMResponse:
        return await self._call_mirascope_v2(Backend.OPENAI, prompt, prompt_model)

    async def _call_google(self, prompt: str, prompt_model: str) -> LLMResponse:
        return await self._call_mirascope_v2(Backend.GOOGLE, prompt, prompt_model)

    async def _call_mirascope_v2(self, backend: Backend, prompt: str, model: str) -> LLMResponse:
        """Appel Mirascope v2 unifié (anthropic/openai/google via `mirascope.llm.call`).

        Utilise la version synchrone de ``llm.call`` exécutée dans un thread
        séparé via ``asyncio.to_thread``. L'API async native de Mirascope v2
        ne supporte pas d'être invoquée à travers plusieurs ``asyncio.run``
        successifs (le client HTTP sous-jacent garde une référence à la
        première boucle event loop).

        Le prompt-caching Anthropic n'est pas encore active : Mirascope v2
        n'expose pas ``cache_control`` via l'API publique ``mirascope.llm``.
        Le module ``providers/anthropic_cache.py`` prepare l'infrastructure
        (detection SDK, structure de messages avec cache_control.ephemeral,
        degradation gracieuse). Quand mirascope v2 exposera cette option, le
        bloc ci-dessous basculera vers ``build_cached_messages(...)``.
        """
        if backend == Backend.ANTHROPIC and self._enable_cache:
            sdk_ok = is_anthropic_sdk_available()
            logger.info(
                "cache_intent",
                extra={
                    "backend": backend.value,
                    "enable_cache": self._enable_cache,
                    "anthropic_sdk_available": sdk_ok,
                    "applied": False,
                    "reason": "mirascope_v2_no_cache_control_api",
                },
            )

        llm = _get_llm()
        model_id = _build_model_id(backend, model)

        def _sync_call() -> Any:
            @llm.call(model_id)
            def _prompt() -> str:
                return prompt

            return _prompt()

        try:
            response = await asyncio.to_thread(_sync_call)
        except Exception as exc:
            self._classify_exception(exc)
            raise

        text = _extract_mirascope_text(response)
        usage = getattr(response, "usage", None)
        if usage is None:
            input_tokens = 0
            output_tokens = 0
            cost = 0.0
        else:
            input_tokens = (
                getattr(usage, "input_tokens", None)
                or getattr(usage, "prompt_tokens", None)
                or getattr(usage, "prompt_token_count", None)
                or 0
            )
            output_tokens = (
                getattr(usage, "output_tokens", None)
                or getattr(usage, "completion_tokens", None)
                or getattr(usage, "candidates_token_count", None)
                or 0
            )
            cost = self._estimate_cost(backend, model, input_tokens, output_tokens)
        return LLMResponse(
            text=text,
            provider=_BACKEND_TO_PROVIDER[backend],
            model=model,
            input_tokens=int(input_tokens or 0),
            output_tokens=int(output_tokens or 0),
            cost_usd=cost,
        )

    def _classify_exception(self, exc: BaseException) -> None:
        """Convertit une exception Mirascope en RateLimitError ou ProviderUnavailableError."""
        try:
            excs = _get_mirascope_exceptions()
        except ImportError:
            return
        names = {RateLimitError, ProviderUnavailableError}
        for name in (RateLimitError, ProviderUnavailableError, Exception):
            cls = getattr(excs, name.__name__, None)
            if cls is not None and isinstance(exc, cls):
                if cls is getattr(excs, "RateLimitError", None):
                    raise RateLimitError(str(exc)) from exc
                if cls is getattr(excs, "AuthenticationError", None):
                    raise ProviderUnavailableError(str(exc)) from exc
                if cls is getattr(excs, "ConnectionError", None):
                    raise ProviderUnavailableError(str(exc)) from exc
                if cls is getattr(excs, "TimeoutError", None):
                    raise ProviderUnavailableError(str(exc)) from exc
                if cls is getattr(excs, "ServerError", None):
                    raise ProviderUnavailableError(str(exc)) from exc
                if cls is getattr(excs, "ProviderError", None):
                    raise ProviderUnavailableError(str(exc)) from exc

    def _estimate_cost(
        self, backend: Backend, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        if backend == Backend.ANTHROPIC:
            prices = ANTHROPIC_PRICES.get(model, (0.0, 0.0))
        elif backend == Backend.OPENAI:
            prices = OPENAI_PRICES.get(model, (0.0, 0.0))
        elif backend == Backend.GOOGLE:
            prices = GOOGLE_PRICES.get(model, (0.0, 0.0))
        else:
            prices = (0.0, 0.0)
        return input_tokens * prices[0] + output_tokens * prices[1]
