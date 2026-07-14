"""Interface de base pour les providers LLM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Reponse d'un provider LLM."""

    text: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    token_count_estimated: bool = False


class BaseProvider(ABC):
    """Interface unifiee pour tous les providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom du provider (ex: 'anthropic', 'openai', 'mock')."""

    @abstractmethod
    def call(
        self,
        prompt: str,
        role: str,
        tier: str = "medium",
    ) -> LLMResponse:
        """Execute un appel LLM.

        Args:
            prompt: Le prompt complet a envoyer.
            role: Le role de l'iteration (producer, critic, adversary, arbiter).
            tier: Le tier de modele souhaite (small, medium, large, xlarge).

        Returns:
            La reponse du LLM.
        """
        ...
