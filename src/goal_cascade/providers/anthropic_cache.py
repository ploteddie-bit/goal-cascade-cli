"""Cache exact Anthropic via prompt-caching.

Section 8.1 / 10 du plan d'implementation v2 : sur un run multi-iterations,
l'objectif + frozen spec + invariants representent ~1200 tokens identiques
repetes 4-5 fois. Le cache exact Anthropic divise par 10 le cout du prefixe.

LIMITATION ACTUELLE (documentee)
---------------------------------
Mirascope v2 (notre couche d'abstraction multi-provider) n'expose pas
``cache_control`` via son API publique ``mirascope.llm``. Voir le
commentaire ligne 362 de ``mirascope_provider.py``.

Ce module prepare l'infrastructure pour quand cette limitation sera levee
(dans mirascope, ou via un appel direct a anthropic SDK) :

1. Detection de la disponibilite du SDK ``anthropic``
2. Construction de la structure de messages avec ``cache_control.ephemeral``
3. Fonction de degradation gracieuse si SDK absent

Quand l'integration reelle sera possible, le caller (MirascopeProvider)
pourra remplacer le bloc docstring actuel par l'appel direct a
``build_cached_messages(...)``.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


_ANTHROPIC_SDK_AVAILABLE: bool | None = None


def is_anthropic_sdk_available() -> bool:
    """Vrai si le SDK ``anthropic`` est installe dans l'environnement.

    Testee une seule fois par process (cache memoire).
    """
    global _ANTHROPIC_SDK_AVAILABLE
    if _ANTHROPIC_SDK_AVAILABLE is None:
        try:
            import anthropic  # noqa: F401

            _ANTHROPIC_SDK_AVAILABLE = True
        except ImportError:
            _ANTHROPIC_SDK_AVAILABLE = False
    return _ANTHROPIC_SDK_AVAILABLE


def build_cached_messages(
    system: str,
    user: str,
    cacheable_prefix: str,
    enable_cache: bool = True,
) -> list[dict[str, Any]]:
    """Construit les messages avec cache_control sur le prefixe stable.

    Args:
        system: texte systeme (instructions generales du role).
        user: prompt utilisateur dynamique (varie entre iterations).
        cacheable_prefix: partie stable du prompt (objectif + frozen spec +
            invariants). C'est ce bloc qui beneficiera du cache.
        enable_cache: si False, retourne des messages bruts sans marqueur.

    Returns:
        Liste de messages au format Anthropic SDK.

    Comportement :
        - Si ``enable_cache=False`` : messages bruts, pas de marqueur.
        - Si SDK ``anthropic`` absent : messages bruts + warning log.
          (Graceful degradation : le code ne leve jamais, il degrade.)
        - Sinon : messages avec bloc cache_control.ephemeral sur le prefixe.
    """
    if not enable_cache:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    if not is_anthropic_sdk_available():
        logger.warning(
            "anthropic_sdk_absent",
            extra={"hint": "pip install goal-cascade[llm] pour activer cache_control"},
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # SDK disponible : on peut structurer les messages avec cache_control
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": cacheable_prefix,
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": user},
            ],
        },
    ]


def split_prompt_for_caching(
    objective: str,
    frozen_spec: str,
    dynamic_suffix: str,
) -> tuple[str, str]:
    """Separe un prompt en (cacheable_prefix, dynamic_suffix).

    Le prefixe (objectif + frozen spec) represente la partie stable
    repetee entre iterations et eligible au cache exact.

    Returns:
        Tuple (cacheable_prefix, dynamic_suffix).
    """
    prefix_parts = []
    if objective.strip():
        prefix_parts.append(f"# Objectif\n{objective.strip()}")
    if frozen_spec.strip():
        prefix_parts.append(f"# Specification gelee\n{frozen_spec.strip()}")
    cacheable_prefix = "\n\n".join(prefix_parts)
    return cacheable_prefix, dynamic_suffix


def estimate_cache_savings(
    tokens_prefix: int,
    iterations: int,
    cost_per_input_token_usd: float,
    cache_discount: float = 0.90,
) -> float:
    """Estime l'economie en USD si le cache exact est active.

    Args:
        tokens_prefix: taille du prefixe cacheable (ex: 1200).
        iterations: nombre d'iterations de la cascade (1 a 5).
        cost_per_input_token_usd: cout par token d'entree (ex: 3e-6 pour Sonnet).
        cache_discount: fraction du cout economisee par le cache (defaut 90%).

    Returns:
        Economie totale en USD sur les ``iterations`` appels.
    """
    full_cost = tokens_prefix * cost_per_input_token_usd * iterations
    saved = full_cost * cache_discount
    return saved


__all__ = [
    "build_cached_messages",
    "estimate_cache_savings",
    "is_anthropic_sdk_available",
    "split_prompt_for_caching",
]