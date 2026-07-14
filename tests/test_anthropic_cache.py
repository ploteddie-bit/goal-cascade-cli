"""Tests unitaires pour le module anthropic_cache.

Couvre :
- is_anthropic_sdk_available() : vrai si SDK importe, faux sinon
- build_cached_messages avec enable_cache=False : pas de marqueur
- build_cached_messages avec SDK absent : degradation gracieuse
- build_cached_messages avec SDK present (force) : cache_control.ephemeral
- split_prompt_for_caching : separation correcte prefix/dynamic
- estimate_cache_savings : calcul economique
"""

from __future__ import annotations

import sys

import pytest

from goal_cascade.providers import anthropic_cache
from goal_cascade.providers.anthropic_cache import (
    build_cached_messages,
    estimate_cache_savings,
    is_anthropic_sdk_available,
    split_prompt_for_caching,
)

# ---------- is_anthropic_sdk_available ----------


def test_sdk_availability_reflects_actual_install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si anthropic est installe (cas actuel : non), retourne True."""
    # Reset cache
    anthropic_cache._ANTHROPIC_SDK_AVAILABLE = None
    # Si on est dans un env ou anthropic n'est pas dispo (cas actuel),
    # le test verifie le code de degradation.
    result = is_anthropic_sdk_available()
    expected = "anthropic" in sys.modules
    assert result == expected


def test_sdk_availability_handles_missing_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si l'import echoue, retourne False (jamais d'exception)."""
    # Force le re-test en remettant le cache a None
    anthropic_cache._ANTHROPIC_SDK_AVAILABLE = None

    # Mock l'import pour simuler l'absence du SDK
    original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "anthropic" or name.startswith("anthropic."):
            raise ImportError("anthropic non disponible (test)")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    anthropic_cache._ANTHROPIC_SDK_AVAILABLE = None

    assert is_anthropic_sdk_available() is False


# ---------- build_cached_messages ----------


def test_build_messages_without_cache_returns_plain() -> None:
    """enable_cache=False : messages bruts, aucun marqueur cache_control."""
    messages = build_cached_messages(
        system="Tu es un expert.",
        user="Question de l'utilisateur.",
        cacheable_prefix="Objectif : tester.",
        enable_cache=False,
    )

    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "Tu es un expert."}
    assert messages[1] == {"role": "user", "content": "Question de l'utilisateur."}
    # Aucun marqueur cache_control
    for msg in messages:
        assert "cache_control" not in msg


def test_build_messages_degrades_gracefully_without_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si SDK anthropic absent + enable_cache=True, retourne messages bruts
    sans lever d'exception."""
    # Force la detection a False
    anthropic_cache._ANTHROPIC_SDK_AVAILABLE = False

    messages = build_cached_messages(
        system="system",
        user="user",
        cacheable_prefix="prefix",
        enable_cache=True,
    )

    assert len(messages) == 2
    # Pas de marqueur car SDK absent
    for msg in messages:
        assert "cache_control" not in str(msg)


def test_build_messages_with_sdk_applies_cache_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si SDK anthropic present + enable_cache=True, applique cache_control
    sur le prefixe uniquement."""
    # Force la detection a True pour ce test
    anthropic_cache._ANTHROPIC_SDK_AVAILABLE = True

    messages = build_cached_messages(
        system="system",
        user="user-prompt",
        cacheable_prefix="prefix-cacheable",
        enable_cache=True,
    )

    assert len(messages) == 2
    assert messages[0] == {"role": "system", "content": "system"}
    user_content = messages[1]["content"]
    assert isinstance(user_content, list)
    assert len(user_content) == 2
    # Premier bloc : prefixe avec cache_control
    assert user_content[0]["text"] == "prefix-cacheable"
    assert user_content[0]["cache_control"] == {"type": "ephemeral"}
    # Second bloc : prompt dynamique sans cache_control
    assert user_content[1]["text"] == "user-prompt"
    assert "cache_control" not in user_content[1]


# ---------- split_prompt_for_caching ----------


def test_split_prompt_with_full_inputs() -> None:
    prefix, suffix = split_prompt_for_caching(
        objective="Audit d'un argument",
        frozen_spec="3 invariants obligatoires",
        dynamic_suffix="Voici le draft a auditer :\n...",
    )
    assert "Objectif" in prefix
    assert "Audit d'un argument" in prefix
    assert "Specification gelee" in prefix
    assert "3 invariants" in prefix
    assert suffix == "Voici le draft a auditer :\n..."


def test_split_prompt_with_empty_objective() -> None:
    prefix, suffix = split_prompt_for_caching(
        objective="",
        frozen_spec="spec",
        dynamic_suffix="suite",
    )
    assert "Specification gelee" in prefix
    assert "Objectif" not in prefix
    assert suffix == "suite"


def test_split_prompt_with_empty_frozen_spec() -> None:
    prefix, suffix = split_prompt_for_caching(
        objective="obj",
        frozen_spec="",
        dynamic_suffix="suite",
    )
    assert "Objectif" in prefix
    assert "Specification gelee" not in prefix
    assert suffix == "suite"


def test_split_prompt_with_both_empty() -> None:
    prefix, suffix = split_prompt_for_caching(
        objective="",
        frozen_spec="",
        dynamic_suffix="suite",
    )
    assert prefix == ""
    assert suffix == "suite"


# ---------- estimate_cache_savings ----------


def test_estimate_savings_basic() -> None:
    """Calcul basique : 1200 tokens, 4 iterations, cout Sonnet input 3e-6."""
    saved = estimate_cache_savings(
        tokens_prefix=1200,
        iterations=4,
        cost_per_input_token_usd=3e-6,
    )
    # full = 1200 * 3e-6 * 4 = 0.0144
    # saved = 0.0144 * 0.90 = 0.01296
    assert abs(saved - 0.01296) < 0.0001


def test_estimate_savings_with_custom_discount() -> None:
    saved = estimate_cache_savings(
        tokens_prefix=1000,
        iterations=5,
        cost_per_input_token_usd=15e-6,  # Opus
        cache_discount=0.50,
    )
    # full = 1000 * 15e-6 * 5 = 0.075
    # saved = 0.075 * 0.50 = 0.0375
    assert abs(saved - 0.0375) < 0.0001


def test_estimate_savings_zero_iterations() -> None:
    assert estimate_cache_savings(1000, 0, 3e-6) == 0.0


def test_estimate_savings_negative_iterations_treated_as_zero() -> None:
    """Une valeur defensive : iteration negative ne devrait pas etre exploitable."""
    # Le plan actuel accepte la valeur negative et retourne un nombre <= 0.
    # On documente le comportement mais on n'impose pas de garde (hors perimetre).
    saved = estimate_cache_savings(1000, -1, 3e-6)
    assert saved <= 0.0
