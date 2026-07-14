"""Détection de dérive par similarité cosinus entre itérations successives.

Utilise OllamaEmbedding (bge-m3:latest, 1024D) avec un timeout court (2s)
pour ne jamais bloquer la cascade. Lecture seule : ne sert JAMAIS de réponse
cachée intra-cascade (section 11.2 du framework).

Seuils (section 11.3 du framework) :
    ≥ 0.95 → CRITICAL  (STOP anticipé, ancrage ou convergence)
    0.85–0.95 → WARNING (forte similarité, vérifier si nouveau contenu)
    0.70–0.85 → NORMAL  (progression dans la même direction)
    < 0.70 → DIVERGENT  (attendu pour l'adversaire, itération 3)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

import numpy as np

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

from goal_cascade.audit_journal import redact_sensitive
from goal_cascade.rag.embed import OllamaEmbedding

DRIFT_TIMEOUT_S = 2.0  # Timeout dédié drift, bien inférieur au sync RAG (180s)

SIMILARITY_THRESHOLDS = {
    "critical": 0.95,
    "warning": 0.85,
    "normal": 0.70,
}


class DriftStatus(str, Enum):
    """Statut de dérive entre deux itérations successives."""

    NO_DATA = "no_data"  # Première itération, pas de comparaison
    NORMAL = "normal"  # 0.70 ≤ sim < 0.85
    WARNING = "warning"  # 0.85 ≤ sim < 0.95
    CRITICAL = "critical"  # sim ≥ 0.95 → STOP anticipé
    DIVERGENT = "divergent"  # sim < 0.70 → attendu adversaire
    ERROR = "error"  # Embedding échoué (timeout, serveur down)


class DriftDetector:
    """Mesure la similarité cosinus entre sorties d'itérations successives.

    Règle absolue : lecture seule. Ne retourne JAMAIS de réponse cachée.
    Utilise le même modèle d'embedding que le RAG (bge-m3:latest) pour
    garantir la cohérence des mesures.
    """

    def __init__(
        self,
        embedding_client: OllamaEmbedding | None = None,
        thresholds: dict[str, float] | None = None,
    ):
        self._client = embedding_client or OllamaEmbedding(timeout=DRIFT_TIMEOUT_S)
        self._thresholds = thresholds or SIMILARITY_THRESHOLDS
        self._previous_embedding: np.ndarray | None = None

    def evaluate(self, text: str) -> tuple[DriftStatus, float | None]:
        """Évalue la dérive par rapport à l'itération précédente.

        Returns:
            Tuple (status, similarity_score).
            similarity_score est None à la première itération ou en cas d'erreur.
        """
        try:
            embedding = self._embed_safe(text)
        except Exception as exc:
            logger.warning(
                "drift_embedding_failed error=%s",
                redact_sensitive(str(exc)),
            )
            return DriftStatus.ERROR, None

        if embedding is None:
            return DriftStatus.ERROR, None

        current = np.array(embedding, dtype=np.float64)

        if self._previous_embedding is None:
            self._previous_embedding = current
            logger.info("drift_first_iteration baseline_stored")
            return DriftStatus.NO_DATA, None

        similarity = self._cosine_similarity(self._previous_embedding, current)
        self._previous_embedding = current

        status = self._classify(similarity)

        logger.info(
            "drift_evaluated similarity=%.4f status=%s",
            similarity,
            status.value,
        )

        return status, similarity

    def reset(self) -> None:
        """Réinitialise l'état (nouvelle cascade)."""
        self._previous_embedding = None

    @property
    def has_baseline(self) -> bool:
        """True si une embedding de référence existe."""
        return self._previous_embedding is not None

    # ── Internes ────────────────────────────────────────────────

    def _embed_safe(self, text: str) -> list[float] | None:
        """Appel embedding avec gestion d'erreur silencieuse.

        L'API OllamaEmbedding.embed() prend un itérable de strings
        et retourne un itérable de np.ndarray. On encapsule l'appel
        pour extraire le premier vecteur.
        """
        try:
            vectors = list(self._client.embed([text]))
            if not vectors:
                return None
            vec = vectors[0]
            # np.ndarray → list[float]
            if hasattr(vec, "tolist"):
                return vec.tolist()
            return list(vec)
        except Exception:
            return None

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Similarité cosinus entre deux vecteurs normalisés."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _classify(self, similarity: float) -> DriftStatus:
        """Classifie la similarité selon les seuils configurés."""
        if similarity >= self._thresholds["critical"]:
            return DriftStatus.CRITICAL
        if similarity >= self._thresholds["warning"]:
            return DriftStatus.WARNING
        if similarity >= self._thresholds["normal"]:
            return DriftStatus.NORMAL
        return DriftStatus.DIVERGENT
