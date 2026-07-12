"""Rate limiting, backoff exponentiel et fallback provider.

Ce module isole la logique de resilience (rate limit + fallback chain)
de la couche d'appel provider (MirascopeProvider). Il est deliberement
independant de tout SDK LLM pour rester testable et reutilisable.

Origine du code : ``mirascope_provider.py`` (versions v0..v7). Voir le
handover ``gpt-handover-goal-rag-20260711`` pour le contexte du refactor.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..audit_journal import redact_sensitive
from .base import LLMResponse
from .families import PROVIDER_FAMILIES

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


class Backend(str, Enum):
    """Backends LLM supportes par le multi-provider.

    Cette enum est la source de verite unique partagee entre
    ``rate_limiter.py`` (fallback chain) et ``mirascope_provider.py``
    (TIER_MODEL_MAP, _BACKEND_TO_PROVIDER).
    """

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


# Constantes exposees pour documentation, reutilisation et tests.
# Ce sont les valeurs par defaut de RateLimitConfig : les utiliser comme
# source unique de verite evite toute divergence entre les champs Pydantic
# et le code qui importe les constantes.
MAX_RETRIES: int = 3
INITIAL_BACKOFF_S: float = 1.0
BACKOFF_MULTIPLIER: float = 2.0


class RateLimitConfig(BaseModel):
    """Configuration du rate limit handler."""

    max_retries: int = Field(default=MAX_RETRIES, ge=1, le=10)
    initial_backoff_s: float = Field(default=INITIAL_BACKOFF_S, gt=0)
    backoff_multiplier: float = Field(default=BACKOFF_MULTIPLIER, gt=1)


# Chaine de fallback par backend primaire. Chaque liste est l'ordre de
# tentative apres epuisement du backend initial.
FALLBACK_CHAIN: dict[Backend, list[Backend]] = {
    Backend.ANTHROPIC: [Backend.OPENAI, Backend.GOOGLE],
    Backend.OPENAI: [Backend.ANTHROPIC, Backend.GOOGLE],
    Backend.GOOGLE: [Backend.ANTHROPIC, Backend.OPENAI],
}


class RateLimitError(Exception):
    """Le provider a retourne une limite de debit (HTTP 429)."""


class ProviderUnavailableError(Exception):
    """Le provider est indisponible ou retourne une erreur serveur."""


class ProviderExhaustedError(Exception):
    """Tous les providers disponibles ont echoue (retry + fallback)."""


# Signature du callable injecte : backend_call(backend, prompt, role, tier)
# doit retourner une LLMResponse ou lever RateLimitError/ProviderUnavailableError.
BackendCall = Callable[[Backend, str, str, str], Awaitable[LLMResponse]]


async def call_with_retry_and_fallback(
    backend_call: BackendCall,
    backend: Backend,
    prompt: str,
    role: str,
    tier: str,
    rate_config: RateLimitConfig,
    available_backends: set[Backend] | None = None,
) -> LLMResponse:
    """Appelle ``backend_call`` avec retry+backoff exponentiel puis fallback.

    Algorithme :
    1. Tente ``max_retries`` fois le backend initial avec backoff
       exponentiel entre chaque tentative en cas de ``RateLimitError``.
    2. Si toutes les tentatives echouent OU si on recoit une
       ``ProviderUnavailableError``, parcourt ``FALLBACK_CHAIN[backend]``
       et tente chaque backend disponible dans ``available_backends``.
    3. Si tous les backends (initial + fallback) echouent, leve
       ``ProviderExhaustedError``.

    La fonction ``backend_call`` est injectee pour permettre des tests
    unitaires deterministes (sans appel reel a un provider).
    """
    if available_backends is None:
        available_backends = set(Backend)

    last_error: Exception | None = None
    for attempt in range(rate_config.max_retries):
        try:
            response = await backend_call(backend, prompt, role, tier)
            logger.info(
                "provider_call_success backend=%s role=%s tier=%s attempt=%d",
                backend.value, role, tier, attempt + 1,
            )
            return response
        except RateLimitError as exc:
            last_error = exc
            if attempt < rate_config.max_retries - 1:
                wait = rate_config.initial_backoff_s * (
                    rate_config.backoff_multiplier ** attempt
                )
                logger.warning(
                    "rate_limit_retry backend=%s role=%s tier=%s attempt=%d wait_s=%.3f",
                    backend.value, role, tier, attempt + 1, wait,
                )
                await asyncio.sleep(wait)
            else:
                logger.error(
                    "rate_limit_exhausted backend=%s role=%s tier=%s max_retries=%d",
                    backend.value, role, tier, rate_config.max_retries,
                )
        except ProviderUnavailableError as exc:
            last_error = exc
            logger.error(
                "provider_unavailable backend=%s role=%s error=%s",
                backend.value, role, redact_sensitive(str(exc)),
            )
            break
    return await _try_fallback(
        backend_call, backend, prompt, role, tier, last_error, available_backends
    )


async def _try_fallback(
    backend_call: BackendCall,
    backend: Backend,
    prompt: str,
    role: str,
    tier: str,
    original_error: Exception | None,
    available_backends: set[Backend],
) -> LLMResponse:
    """Parcourt la chaine de fallback et leve ProviderExhaustedError si tout echoue.

    Regle de diversite (Pilier 1) : un fallback vers un provider de la meme
    famille que le backend primaire est refuse. Si la chaine entiere est dans
    la meme famille (cas theorique mais explicitement defendu), on leve
    ``ProviderExhaustedError`` comme si tous les backends avaient echoue.
    """
    primary_family = PROVIDER_FAMILIES.get(backend.value, backend.value)
    for fallback_backend in FALLBACK_CHAIN.get(backend, []):
        if fallback_backend not in available_backends:
            continue
        # Defense en profondeur : refuser le fallback si meme famille
        fallback_family = PROVIDER_FAMILIES.get(
            fallback_backend.value, fallback_backend.value
        )
        if fallback_family == primary_family:
            logger.warning(
                "provider_fallback_skipped from=%s to=%s reason=same_family",
                backend.value, fallback_backend.value,
            )
            continue
        try:
            logger.warning(
                "provider_fallback from=%s to=%s role=%s tier=%s",
                backend.value, fallback_backend.value, role, tier,
            )
            response = await backend_call(fallback_backend, prompt, role, tier)
            logger.info(
                "fallback_success backend=%s role=%s tier=%s",
                fallback_backend.value, role, tier,
            )
            return response
        except Exception as exc:
            logger.error(
                "fallback_failed backend=%s role=%s error=%s",
                fallback_backend.value, role, redact_sensitive(str(exc)),
            )
    raise ProviderExhaustedError(
        f"Tous les providers epuises pour {backend.value}. "
        f"Derniere erreur : {original_error}"
    )