"""Cache sémantique inter-runs (spec V2 §8.2 + framework §11.2).

RÈGLE ABSOLUE : lecture seule intra-cascade. Ne sert JAMAIS de réponse
cachée à l'intérieur d'une cascade. Uniquement pour :
  1. Réutilisation transverse entre runs (synthèses, artefacts)
  2. Détection de dérive (via DriftDetector)

Stockage : SQLite local (~/.goal/semantic_cache.db)
Embeddings : bge-m3:latest sur ia-general (1024D, timeout 2s)
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

from ..audit_journal import redact_sensitive
from ..rag.embed import OllamaEmbedding
from .state_manager import ensure_private_dir

CACHE_DB_PATH = Path.home() / ".goal" / "semantic_cache.db"
EMBEDDING_DIM = 1024
SIMILARITY_THRESHOLD = 0.92  # Seuil de match sémantique

# Permissions restrictives pour la DB SQLite locale (E3).
CACHE_DB_MODE = 0o600
CACHE_DIR_MODE = 0o700


class SemanticCache:
    """Cache sémantique SQLite + embeddings bge-m3.

    Usage typique :
        cache = SemanticCache()
        # Entre deux runs (pas intra-cascade)
        cached = cache.lookup("Quelle est la stratégie marketing ?")
        if cached:
            print(f"Réutilisé depuis run {cached['run_id']}")
        else:
            result = run_cascade(...)
            cache.store("Quelle est la stratégie marketing ?", result, run_id="abc123")
    """

    def __init__(
        self,
        db_path: Path | None = None,
        embedding_client: OllamaEmbedding | None = None,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ):
        self._db_path = db_path or CACHE_DB_PATH
        self._client = embedding_client or OllamaEmbedding(timeout=2.0)
        self._threshold = similarity_threshold
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Crée la table si elle n'existe pas, avec permissions restreintes."""
        ensure_private_dir(self._db_path.parent, mode=CACHE_DIR_MODE)
        with sqlite3.connect(str(self._db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query_hash TEXT NOT NULL UNIQUE,
                    query_text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    result_json TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    access_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_query_hash
                ON semantic_entries(query_hash)
            """)
            conn.commit()
        try:
            self._db_path.chmod(CACHE_DB_MODE)
        except OSError:
            # FS ne supporte pas chmod : ignorer (ex: certains mounts Windows).
            pass

    # ── Lookup (lecture seule) ──────────────────────────────────

    def lookup(self, query: str) -> dict[str, Any] | None:
        """Recherche une entrée sémantiquement similaire.

        Returns:
            Dict avec 'result', 'run_id', 'similarity' si trouvé, None sinon.
            Retourne None en cas d'erreur embedding (pas de blocage).
        """
        try:
            query_embedding = self._embed_safe(query)
        except Exception as exc:
            logger.warning(
                "semantic_cache_lookup_embedding_failed error=%s",
                redact_sensitive(str(exc)),
            )
            return None

        if query_embedding is None:
            return None

        query_vec = np.array(query_embedding, dtype=np.float64)
        best_match: dict[str, Any] | None = None
        best_similarity = 0.0

        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute("SELECT embedding, result_json, run_id FROM semantic_entries")
            for row in cursor:
                stored_vec = np.frombuffer(row[0], dtype=np.float64)
                similarity = self._cosine_similarity(query_vec, stored_vec)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = {
                        "result": json.loads(row[1]),
                        "run_id": row[2],
                        "similarity": similarity,
                    }

        if best_match and best_similarity >= self._threshold:
            logger.info(
                "semantic_cache_hit similarity=%.4f run_id=%s threshold=%.2f",
                best_similarity,
                best_match["run_id"],
                self._threshold,
            )
            self._increment_access(best_match["run_id"])
            return best_match

        logger.debug(
            "semantic_cache_miss best_similarity=%.4f threshold=%.2f",
            best_similarity,
            self._threshold,
        )
        return None

    # ── Store (écriture) ────────────────────────────────────────

    def store(self, query: str, result: Any, run_id: str) -> bool:
        """Stocke une entrée dans le cache sémantique.

        Args:
            query: La requête/objectif original.
            result: Le résultat à cacher (doit être JSON-sérialisable).
            run_id: L'identifiant du run source.

        Returns:
            True si stocké avec succès, False en cas d'erreur.
        """
        try:
            embedding = self._embed_safe(query)
        except Exception as exc:
            logger.warning(
                "semantic_cache_store_embedding_failed error=%s",
                redact_sensitive(str(exc)),
            )
            return False

        if embedding is None:
            return False

        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        embedding_blob = np.array(embedding, dtype=np.float64).tobytes()
        result_json = json.dumps(result, ensure_ascii=False)
        now = datetime.now(timezone.utc).isoformat()

        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO semantic_entries
                       (query_hash, query_text, embedding, result_json, run_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (query_hash, query, embedding_blob, result_json, run_id, now),
                )
                conn.commit()
            logger.info(
                "semantic_cache_stored hash=%s run_id=%s dim=%d",
                query_hash,
                run_id,
                EMBEDDING_DIM,
            )
            return True
        except sqlite3.Error as exc:
            logger.error(
                "semantic_cache_store_db_error error=%s",
                redact_sensitive(str(exc)),
            )
            return False

    # ── Stats et nettoyage ──────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Retourne les statistiques du cache."""
        with sqlite3.connect(str(self._db_path)) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(access_count), 0) FROM semantic_entries"
            ).fetchone()
            total_entries = row[0]
            total_accesses = row[1]

        return {
            "total_entries": total_entries,
            "total_accesses": total_accesses,
            "embedding_dim": EMBEDDING_DIM,
            "similarity_threshold": self._threshold,
            "db_path": str(self._db_path),
        }

    def clear(self) -> int:
        """Supprime toutes les entrées du cache.

        Returns:
            Nombre d'entrées supprimées.
        """
        with sqlite3.connect(str(self._db_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM semantic_entries")
            count = cursor.fetchone()[0]
            conn.execute("DELETE FROM semantic_entries")
            conn.commit()
        logger.info("semantic_cache_cleared entries=%d", count)
        return count

    # ── Internes ────────────────────────────────────────────────

    def _embed_safe(self, text: str) -> list[float] | None:
        """Appel embedding avec gestion d'erreur silencieuse."""
        try:
            vectors = list(self._client.embed([text]))
            if not vectors:
                return None
            vec = vectors[0]
            if hasattr(vec, "tolist"):
                return vec.tolist()
            return list(vec)
        except Exception as exc:
            logger.warning(
                "semantic_cache_embedding_failed error=%s",
                redact_sensitive(str(exc)),
            )
            return None

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Similarité cosinus entre deux vecteurs."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def _increment_access(self, run_id: str) -> None:
        """Incrémente le compteur d'accès pour une entrée."""
        try:
            with sqlite3.connect(str(self._db_path)) as conn:
                conn.execute(
                    "UPDATE semantic_entries SET access_count = access_count + 1 WHERE run_id = ?",
                    (run_id,),
                )
                conn.commit()
        except sqlite3.Error:
            pass  # Non critique
