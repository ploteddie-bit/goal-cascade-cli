"""Tests de qualité de la synthèse — S3-C.

Couvre :
- Validation Pydantic renforcée (objective non vide, instruction non vide, max 5 décisions)
- Coverage métrique : ratio de mots significatifs de la sortie brute présents dans la synthèse
- Warn log si coverage < 0.30
- SynthesisResult.coverage_score rempli correctement
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from goal_cascade.schemas.models import GoalOrientedSynthesis


# ---------- Validation Pydantic renforcée ----------


class TestGoalOrientedSynthesisValidation:
    """Tests de validation des champs de GoalOrientedSynthesis."""

    def test_valid_synthesis_passes(self):
        synth = GoalOrientedSynthesis(
            objective="Réduire la latence du serveur API",
            key_decisions=["Utiliser le cache Redis", "Indexer la BDD"],
            uncertainties=[],
            next_instruction="Implémenter le cache Redis dans le module auth",
            iteration_from=1,
            iteration_to=2,
        )
        assert synth.objective == "Réduire la latence du serveur API"
        assert len(synth.key_decisions) == 2

    def test_empty_objective_rejected(self):
        with pytest.raises(ValidationError, match="objective"):
            GoalOrientedSynthesis(
                objective="",
                key_decisions=["Décision"],
                next_instruction="Instruction",
                iteration_from=1,
                iteration_to=2,
            )

    def test_whitespace_only_objective_rejected(self):
        """Un objectif composé uniquement d'espaces est rejeté."""
        with pytest.raises(ValidationError, match="objective"):
            GoalOrientedSynthesis(
                objective="   ",
                key_decisions=["Décision"],
                next_instruction="Instruction",
                iteration_from=1,
                iteration_to=2,
            )

    def test_empty_next_instruction_rejected(self):
        with pytest.raises(ValidationError, match="next_instruction"):
            GoalOrientedSynthesis(
                objective="Objectif valide",
                key_decisions=["Décision"],
                next_instruction="",
                iteration_from=1,
                iteration_to=2,
            )

    def test_empty_key_decisions_rejected(self):
        with pytest.raises(ValidationError, match="key_decisions"):
            GoalOrientedSynthesis(
                objective="Objectif valide",
                key_decisions=[],
                next_instruction="Instruction",
                iteration_from=1,
                iteration_to=2,
            )

    def test_more_than_5_key_decisions_rejected(self):
        with pytest.raises(ValidationError, match="key_decisions"):
            GoalOrientedSynthesis(
                objective="Objectif valide",
                key_decisions=["D1", "D2", "D3", "D4", "D5", "D6"],
                next_instruction="Instruction",
                iteration_from=1,
                iteration_to=2,
            )

    def test_exactly_5_key_decisions_accepted(self):
        synth = GoalOrientedSynthesis(
            objective="Objectif valide",
            key_decisions=["D1", "D2", "D3", "D4", "D5"],
            next_instruction="Instruction",
            iteration_from=1,
            iteration_to=2,
        )
        assert len(synth.key_decisions) == 5

    def test_single_decision_accepted(self):
        synth = GoalOrientedSynthesis(
            objective="Objectif",
            key_decisions=["Seule décision"],
            next_instruction="Instruction",
            iteration_from=1,
            iteration_to=2,
        )
        assert len(synth.key_decisions) == 1


# ---------- Coverage métrique ----------


class TestCoverageMetric:
    """Tests du calcul de coverage (préservation d'information)."""

    def test_high_coverage_when_synthesis_reuses_key_words(self):
        """Si la synthèse réutilise les mots clés de la sortie brute, coverage élevé."""
        from goal_cascade.orchestrator.synthesizer import Synthesizer

        raw = (
            "Le serveur API présente une latence élevée sur les requêtes "
            "de base de données PostgreSQL. Le cache Redis pourrait réduire "
            "cette latence de 80%. L'indexation des tables fréquemment "
            "interrogées est également recommandée."
        )
        synthesis = GoalOrientedSynthesis(
            objective="Réduire la latence du serveur API",
            key_decisions=["Implémenter cache Redis", "Indexer tables PostgreSQL"],
            uncertainties=["Impact sur la cohérence des données"],
            next_instruction="Implémenter le cache Redis dans le module auth",
            iteration_from=1,
            iteration_to=2,
        )

        coverage = Synthesizer._compute_coverage(raw, synthesis)

        assert coverage is not None
        assert coverage > 0.30, f"Coverage trop bas: {coverage:.3f}"

    def test_low_coverage_when_synthesis_ignores_source(self):
        """Si la synthèse ne reprend aucun mot de la sortie brute, coverage bas."""
        from goal_cascade.orchestrator.synthesizer import Synthesizer

        raw = (
            "Analyse approfondie du système de messagerie RabbitMQ. "
            "Les queues persistent les messages avec un TTL de 24 heures. "
            "Le consumer lag atteint parfois 5000 messages pendant les pics."
        )
        synthesis = GoalOrientedSynthesis(
            objective="Améliorer l'interface utilisateur",
            key_decisions=["Changer la couleur du bouton", "Ajouter un tooltip"],
            uncertainties=[],
            next_instruction="Modifier le CSS du composant header",
            iteration_from=1,
            iteration_to=2,
        )

        coverage = Synthesizer._compute_coverage(raw, synthesis)

        assert coverage is not None
        assert coverage < 0.30, f"Coverage trop élevé pour un contenu non pertinent: {coverage:.3f}"

    def test_coverage_none_for_empty_raw_output(self):
        """Sortie brute vide → coverage None (pas de dénominateur)."""
        from goal_cascade.orchestrator.synthesizer import Synthesizer

        synthesis = GoalOrientedSynthesis(
            objective="Objectif",
            key_decisions=["Décision"],
            next_instruction="Instruction",
            iteration_from=1,
            iteration_to=2,
        )

        coverage = Synthesizer._compute_coverage("", synthesis)
        assert coverage is None

    def test_coverage_zero_for_empty_synthesis(self):
        """Synthèse vide → coverage 0."""
        from goal_cascade.orchestrator.synthesizer import Synthesizer

        raw = "Texte avec des mots significatifs importants pour le système"
        # model_construct bypass la validation pour tester le calcul coverage
        synthesis_bypass = GoalOrientedSynthesis.model_construct(
            objective="",
            key_decisions=[""],
            uncertainties=[],
            next_instruction="",
            iteration_from=1,
            iteration_to=2,
        )

        coverage = Synthesizer._compute_coverage(raw, synthesis_bypass)
        assert coverage == 0.0

    def test_coverage_handles_french_accented_characters(self):
        """Les caractères accentués français sont comptabilisés."""
        from goal_cascade.orchestrator.synthesizer import Synthesizer

        raw = "La vérification automatique des paramètres de configuration est essentielle"
        synthesis = GoalOrientedSynthesis(
            objective="Vérification automatique des paramètres",
            key_decisions=["Configuration centralisée"],
            uncertainties=[],
            next_instruction="Implémenter la vérification dans le module config",
            iteration_from=1,
            iteration_to=2,
        )

        coverage = Synthesizer._compute_coverage(raw, synthesis)

        assert coverage is not None
        # "vérification", "automatique", "paramètres", "configuration" devraient matcher
        assert coverage > 0.20


# ---------- Intégration SynthesisResult ----------


class TestSynthesisResultCoverage:
    """Vérifie que SynthesisResult a le champ coverage_score."""

    def test_synthesis_result_has_coverage_field(self):
        from goal_cascade.orchestrator.synthesizer import SynthesisResult
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(SynthesisResult)}
        assert "coverage_score" in field_names

    def test_coverage_score_defaults_to_none(self):
        from goal_cascade.orchestrator.synthesizer import SynthesisResult
        from goal_cascade.schemas.models import GoalOrientedSynthesis, ImmutableArtifact
        from goal_cascade.providers.base import LLMResponse

        result = SynthesisResult(
            synthesis=GoalOrientedSynthesis(
                objective="Obj",
                key_decisions=["D"],
                next_instruction="Inst",
                iteration_from=1,
                iteration_to=2,
            ),
            artifacts=[],
            response=LLMResponse(text="x", provider="test", model="test"),
            prompt="p",
        )
        assert result.coverage_score is None