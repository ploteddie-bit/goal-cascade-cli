"""Tests du cache sémantique (spec V2 §8.2).

Structure : fixtures pytest, classes logiques, mock embedding client.
Couvre : store/lookup exact, miss, remplacement, résilience erreurs, stats/clear.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from goal_cascade.orchestrator.semantic_cache import SemanticCache


# ── Helper ────────────────────────────────────────────────────────


def _make_unit_vector(dim: int = 1024, seed: int = 0) -> list[float]:
    """Génère un vecteur unitaire déterministe de dimension *dim*."""
    rng = np.random.RandomState(seed)
    vec = rng.randn(dim).astype(np.float64)
    vec /= np.linalg.norm(vec)
    return vec.tolist()


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def mock_embedding_client() -> MagicMock:
    """Client embedding factice qui retourne un vecteur unitaire fixe."""
    client = MagicMock()
    client.embed.return_value = [_make_unit_vector(dim=1024, seed=0)]
    return client


@pytest.fixture
def cache(tmp_path, mock_embedding_client: MagicMock) -> SemanticCache:
    """SemanticCache SQLite temporaire avec client mocké, threshold=0.90."""
    db_path = tmp_path / "test_semantic_cache.db"
    return SemanticCache(
        db_path=db_path,
        embedding_client=mock_embedding_client,
        similarity_threshold=0.90,
    )


# ── Store & Lookup ────────────────────────────────────────────────


class TestSemanticCacheStoreAndLookup:
    """Tests de base : stockage, lookup exact, miss, remplacement."""

    def test_store_and_lookup_exact_match(self, cache: SemanticCache) -> None:
        """store puis lookup du même texte → trouvé avec similarité >= threshold."""
        result = {"answer": "42", "confidence": 0.99}
        assert cache.store("Quelle est la réponse ?", result, run_id="run-001") is True

        found = cache.lookup("Quelle est la réponse ?")
        assert found is not None
        assert found["result"] == result
        assert found["run_id"] == "run-001"
        assert found["similarity"] >= 0.90

    def test_lookup_miss_returns_none(self, cache: SemanticCache) -> None:
        """Deux textes orthogonaux (embeddings différents) → None."""
        # Stocke avec seed=0
        cache.store("Recette du gâteau au chocolat", {"data": "choco"}, run_id="run-10")

        # Lookup avec un vecteur orthogonal (seed=1)
        client_orthogonal = MagicMock()
        client_orthogonal.embed.return_value = [_make_unit_vector(dim=1024, seed=1)]
        cache._client = client_orthogonal

        found = cache.lookup("Politique monétaire de la BCE")
        assert found is None

    def test_store_replaces_same_query_hash(self, cache: SemanticCache) -> None:
        """Même texte stocké deux fois → la valeur est mise à jour (INSERT OR REPLACE)."""
        cache.store("Objectif Q3", {"target": 100}, run_id="run-A")
        cache.store("Objectif Q3", {"target": 200}, run_id="run-B")

        found = cache.lookup("Objectif Q3")
        assert found is not None
        assert found["result"]["target"] == 200
        assert found["run_id"] == "run-B"


# ── Résilience erreurs ────────────────────────────────────────────


class TestSemanticCacheResilience:
    """Tests de robustesse quand le client embedding échoue."""

    def test_lookup_returns_none_on_embedding_failure(
        self, cache: SemanticCache, mock_embedding_client: MagicMock
    ) -> None:
        """TimeoutError sur embed → lookup retourne None sans lever."""
        mock_embedding_client.embed.side_effect = TimeoutError("Ollama timeout")

        result = cache.lookup("test query")
        assert result is None

    def test_store_returns_false_on_embedding_failure(
        self, cache: SemanticCache, mock_embedding_client: MagicMock
    ) -> None:
        """ConnectionRefusedError sur embed → store retourne False sans lever."""
        mock_embedding_client.embed.side_effect = ConnectionRefusedError(
            "Ollama unreachable"
        )

        ok = cache.store("test query", {"x": 1}, run_id="run-err")
        assert ok is False


# ── Stats & Clear ─────────────────────────────────────────────────


class TestSemanticCacheStats:
    """Tests des statistiques et du nettoyage du cache."""

    def test_stats_empty_cache(self, cache: SemanticCache) -> None:
        """Cache vierge → total_entries=0, total_accesses=0."""
        stats = cache.get_stats()
        assert stats["total_entries"] == 0
        assert stats["total_accesses"] == 0

    def test_stats_after_store_and_lookup(self, cache: SemanticCache) -> None:
        """Après 1 store + 1 lookup → total_entries=1, total_accesses=1."""
        cache.store("question A", {"a": 1}, run_id="run-s1")
        cache.lookup("question A")

        stats = cache.get_stats()
        assert stats["total_entries"] == 1
        assert stats["total_accesses"] == 1

    def test_clear_removes_all_entries(self, cache: SemanticCache) -> None:
        """clear() sur 2 entrées → removed=2, cache vide ensuite."""
        cache.store("q1", {"v": 1}, run_id="r1")
        cache.store("q2", {"v": 2}, run_id="r2")

        removed = cache.clear()
        assert removed == 2

        stats = cache.get_stats()
        assert stats["total_entries"] == 0
