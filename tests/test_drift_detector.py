"""Tests du DriftDetector — sans appel réseau (mock OllamaEmbedding).

Couvre :
- Classification par seuils (NO_DATA, CRITICAL, WARNING, NORMAL, DIVERGENT)
- Résilience (timeout, connection refusée, recovery)
- Reset et cycle de vie du baseline
- Validation du timeout dédié (2s) vs défaut RAG (180s)
- Intégration Synthesizer → SynthesisResult.drift_status
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from goal_cascade.orchestrator.drift_detector import (
    DRIFT_TIMEOUT_S,
    SIMILARITY_THRESHOLDS,
    DriftDetector,
    DriftStatus,
)


@pytest.fixture
def mock_embedding_client():
    """Client mock qui retourne des embeddings contrôlés."""
    client = MagicMock()
    return client


@pytest.fixture
def detector(mock_embedding_client):
    return DriftDetector(embedding_client=mock_embedding_client)


def _make_unit_vector(dim: int = 1024, seed: int = 0) -> list[float]:
    """Crée un vecteur unitaire déterministe pour les tests."""
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim)
    v = v / np.linalg.norm(v)
    return v.tolist()


def _wrap_embed(client: MagicMock, vectors: list[list[float]]) -> None:
    """Configure le mock pour que embed() retourne les vecteurs donnés.

    OllamaEmbedding.embed() prend un itérable de strings et retourne
    un itérable de np.ndarray. On simule ce contrat.
    """
    ndarray_vecs = [np.array(v, dtype=np.float32) for v in vectors]
    client.embed.side_effect = [[vec] for vec in ndarray_vecs]


# ---------- Classification par seuils ----------


class TestDriftClassification:
    """Tests de classification par seuils."""

    def test_first_iteration_returns_no_data(self, detector, mock_embedding_client):
        _wrap_embed(mock_embedding_client, [_make_unit_vector(seed=1)])

        status, score = detector.evaluate("premier texte")

        assert status == DriftStatus.NO_DATA
        assert score is None
        assert detector.has_baseline is True

    def test_identical_texts_return_critical(self, detector, mock_embedding_client):
        vec = _make_unit_vector(seed=42)
        _wrap_embed(mock_embedding_client, [vec, vec])

        detector.evaluate("texte A")
        status, score = detector.evaluate("texte A identique")

        assert status == DriftStatus.CRITICAL
        assert score is not None
        assert score >= SIMILARITY_THRESHOLDS["critical"]

    def test_similar_texts_return_warning(self, detector, mock_embedding_client):
        rng = np.random.default_rng(100)
        base = np.array(_make_unit_vector(seed=10))
        # En 1024D, cos(v, v+ε) ≈ 1/√(1+1024σ²). Pour WARNING (0.85-0.95) :
        # σ ≈ 0.015-0.02
        noisy = base + rng.standard_normal(1024) * 0.018
        noisy = noisy / np.linalg.norm(noisy)

        _wrap_embed(mock_embedding_client, [base.tolist(), noisy.tolist()])

        detector.evaluate("texte original")
        status, score = detector.evaluate("texte légèrement modifié")

        assert status == DriftStatus.WARNING
        assert SIMILARITY_THRESHOLDS["warning"] <= score < SIMILARITY_THRESHOLDS["critical"]

    def test_divergent_texts_return_divergent(self, detector, mock_embedding_client):
        # Vecteurs orthogonaux → similarité ~0
        v1 = _make_unit_vector(seed=1)
        v2 = _make_unit_vector(seed=999)

        _wrap_embed(mock_embedding_client, [v1, v2])

        detector.evaluate("texte producteur")
        status, score = detector.evaluate("texte adversaire contradictoire")

        assert status == DriftStatus.DIVERGENT
        assert score is not None
        assert score < SIMILARITY_THRESHOLDS["normal"]

    def test_normal_progression(self, detector, mock_embedding_client):
        rng = np.random.default_rng(200)
        base = np.array(_make_unit_vector(seed=20))
        # En 1024D, pour NORMAL (0.70-0.85) : σ ≈ 0.025-0.035
        evolved = base + rng.standard_normal(1024) * 0.03
        evolved = evolved / np.linalg.norm(evolved)

        _wrap_embed(mock_embedding_client, [base.tolist(), evolved.tolist()])

        detector.evaluate("version 1")
        status, score = detector.evaluate("version 2 améliorée")

        assert status == DriftStatus.NORMAL
        assert SIMILARITY_THRESHOLDS["normal"] <= score < SIMILARITY_THRESHOLDS["warning"]


# ---------- Résilience ----------


class TestDriftErrorHandling:
    """Tests de résilience quand l'embedding échoue."""

    def test_timeout_returns_error_status(self, detector, mock_embedding_client):
        mock_embedding_client.embed.side_effect = TimeoutError("2s exceeded")

        status, score = detector.evaluate("texte")

        assert status == DriftStatus.ERROR
        assert score is None

    def test_connection_refused_returns_error_status(
        self, detector, mock_embedding_client
    ):
        mock_embedding_client.embed.side_effect = ConnectionRefusedError(
            "ia-general down"
        )

        status, score = detector.evaluate("texte")

        assert status == DriftStatus.ERROR
        assert score is None

    def test_error_does_not_update_baseline(self, detector, mock_embedding_client):
        mock_embedding_client.embed.side_effect = TimeoutError("fail")

        detector.evaluate("texte")

        assert detector.has_baseline is False

    def test_recovery_after_error(self, detector, mock_embedding_client):
        # Premier appel échoue, deuxième réussit
        mock_embedding_client.embed.side_effect = [
            TimeoutError("fail"),
            [np.array(_make_unit_vector(seed=1), dtype=np.float32)],
        ]

        status1, _ = detector.evaluate("texte 1")
        status2, _ = detector.evaluate("texte 2")

        assert status1 == DriftStatus.ERROR
        assert status2 == DriftStatus.NO_DATA  # baseline stockée au 2e appel
        assert detector.has_baseline is True


# ---------- Reset ----------


class TestDriftReset:
    """Tests de réinitialisation."""

    def test_reset_clears_baseline(self, detector, mock_embedding_client):
        _wrap_embed(mock_embedding_client, [_make_unit_vector(seed=1)])

        detector.evaluate("texte")
        assert detector.has_baseline is True

        detector.reset()
        assert detector.has_baseline is False

    def test_after_reset_next_evaluate_is_no_data(
        self, detector, mock_embedding_client
    ):
        # return_value au lieu de side_effect pour supporter plusieurs appels
        vec = np.array(_make_unit_vector(seed=1), dtype=np.float32)
        mock_embedding_client.embed.return_value = [vec]

        detector.evaluate("texte 1")
        detector.reset()
        status, score = detector.evaluate("texte 2")

        assert status == DriftStatus.NO_DATA
        assert score is None


# ---------- Validation timeout ----------


class TestOllamaEmbeddingTimeout:
    """Vérifie que OllamaEmbedding accepte le paramètre timeout."""

    def test_default_timeout_is_180(self):
        from goal_cascade.rag.embed import OllamaEmbedding

        client = OllamaEmbedding()
        assert client.timeout == 180

    def test_custom_timeout_for_drift(self):
        from goal_cascade.rag.embed import OllamaEmbedding

        client = OllamaEmbedding(timeout=2.0)
        assert client.timeout == 2.0

    def test_drift_timeout_constant_is_2s(self):
        assert DRIFT_TIMEOUT_S == 2.0

    def test_drift_detector_uses_short_timeout_by_default(self):
        """Sans client explicite, DriftDetector crée un client avec timeout=2s."""
        with patch(
            "goal_cascade.orchestrator.drift_detector.OllamaEmbedding"
        ) as MockCls:
            mock_instance = MagicMock()
            MockCls.return_value = mock_instance

            DriftDetector()

            MockCls.assert_called_once_with(timeout=DRIFT_TIMEOUT_S)


# ---------- Intégration Synthesizer ----------


class TestSynthesizerDriftIntegration:
    """Vérifie que Synthesizer intègre le drift detector correctement."""

    def test_synthesis_result_has_drift_fields(self):
        from goal_cascade.orchestrator.synthesizer import SynthesisResult

        # Vérifier que SynthesisResult a les nouveaux champs
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(SynthesisResult)}
        assert "similarity_score" in field_names
        assert "drift_status" in field_names

    def test_synthesizer_accepts_drift_detector_param(self):
        """Le constructeur de Synthesizer accepte drift_detector optionnel."""
        from goal_cascade.orchestrator.synthesizer import Synthesizer
        from goal_cascade.providers.mock import MockProvider
        from goal_cascade.prompts import PromptLoader

        mock_det = MagicMock()
        synth = Synthesizer(
            provider=MockProvider(),
            prompt_loader=PromptLoader(),
            drift_detector=mock_det,
        )
        assert synth.drift_detector is mock_det

    def test_synthesizer_default_drift_detector_is_none(self):
        """Sans drift_detector explicite, aucun DriftDetector n'est créé.

        Évite qu'une simple création de Synthesizer déclenche une connexion
        réseau. Le CascadeExecutor injecte explicitement un DriftDetector
        quand la détection de dérive est activée.
        """
        from goal_cascade.orchestrator.synthesizer import Synthesizer
        from goal_cascade.providers.mock import MockProvider
        from goal_cascade.prompts import PromptLoader

        synth = Synthesizer(
            provider=MockProvider(),
            prompt_loader=PromptLoader(),
        )
        assert synth.drift_detector is None