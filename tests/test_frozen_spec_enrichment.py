"""Tests de l'enrichissement LLM des frozen specs (--enrich-frozen-specs).

Contrat respecté :
- Chaque invariant généré a verified=False et source="llm-generated".
- L'invariant squelettique (source="auto-from-planning") reste en premier
  pour traçabilité.
- Un échec du LLM sur un module conserve l'invariant squelettique et
  ajoute le module à modules_failed.
- Aucun invariant llm-generated ne passe en verified=True automatiquement.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from goal_cascade.cli import app
from goal_cascade.multicascade.module_graph import ModuleGraph
from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.schemas.models import FrozenSpec, Invariant
from goal_cascade.schemas.plan import CascadePlan, DependencySpec, ModuleSpec


# ── Fixtures ─────────────────────────────────────────────────────


class _ScriptedProvider(BaseProvider):
    """Provider qui joue un script de réponses selon le contenu du prompt."""

    def __init__(self, scripts: dict[str, str]) -> None:
        self.scripts = scripts
        self.calls: list[str] = []
        self._name = "scripted"

    @property
    def name(self) -> str:
        return self._name

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        self.calls.append(prompt)
        for key, response in self.scripts.items():
            if key in prompt:
                return LLMResponse(text=response, provider=self._name, model=f"test-{tier}")
        raise AssertionError(f"Aucun script ne correspond au prompt reçu : {prompt[:120]!r}")


def _make_module(id_: str, name: str, responsibility: str) -> ModuleSpec:
    return ModuleSpec(
        id=id_,
        name=name,
        responsibility=responsibility,
        estimated_lines=500,
    )


def _make_plan(modules: list[ModuleSpec]) -> CascadePlan:
    return CascadePlan(
        objective="Objectif global de test",
        modules=modules,
        dependencies=[],
        total_estimated_lines=sum(m.estimated_lines for m in modules),
    )


def _build_graph_with_skeletal(modules: list[ModuleSpec]) -> tuple[ModuleGraph, CascadePlan]:
    """Construit un ModuleGraph avec des frozen specs squelettiques."""
    plan = _make_plan(modules)
    graph = ModuleGraph()
    for mod in modules:
        skeletal = Invariant(
            description=mod.responsibility,
            category="functional",
            verified=False,
            source="auto-from-planning",
        )
        frozen = FrozenSpec(
            module_name=mod.name,
            objective=mod.responsibility,
            invariants=[skeletal],
            max_lines=mod.estimated_lines,
        )
        graph.add_module(mod.id, frozen)
    return graph, plan


# ── Tests de _enrich_frozen_specs ────────────────────────────────


class TestEnrichFrozenSpecs:
    def test_enrich_adds_llm_generated_invariants(self) -> None:
        """Le 2e appel LLM ajoute 3-5 invariants llm-generated par module."""
        modules = [_make_module("M1", "Auth", "authentifier les utilisateurs")]
        graph, plan = _build_graph_with_skeletal(modules)

        enrich_response = json.dumps(
            {
                "invariants": [
                    {
                        "description": "Toute requête sans token retourne 401",
                        "category": "non_negotiable",
                        "test_hint": "test_auth_missing_token_returns_401",
                    },
                    {
                        "description": "Le token expiré est rejeté avec 401",
                        "category": "functional",
                        "test_hint": "test_auth_expired_token",
                    },
                    {
                        "description": "Le hash bcrypt a un cost factor ≥ 12",
                        "category": "structural",
                        "test_hint": "test_auth_bcrypt_cost",
                    },
                ]
            }
        )
        provider = _ScriptedProvider({"MODULE :": enrich_response})

        stats = ModuleGraph._enrich_frozen_specs(graph, plan, provider)

        stats = ModuleGraph._enrich_frozen_specs(graph, plan, provider)

        frozen = graph._specs["M1"]
        assert stats["modules_enriched"] == 1
        assert stats["invariants_generated"] == 3
        assert stats["modules_failed"] == []

        # L'invariant squelettique reste en premier.
        assert frozen.invariants[0].source == "auto-from-planning"
        assert frozen.invariants[0].verified is False

        # Les 3 nouveaux sont llm-generated et verified=False.
        for inv in frozen.invariants[1:]:
            assert inv.source == "llm-generated"
            assert inv.verified is False

    def test_no_llm_generated_invariant_ever_passes_verified_true(self) -> None:
        """Aucun invariant llm-generated ne passe en verified=True."""
        modules = [_make_module("M1", "Auth", "authentifier")]
        graph, plan = _build_graph_with_skeletal(modules)

        enrich_response = json.dumps(
            {
                "invariants": [
                    {"description": "Invariant A", "category": "functional"},
                    {"description": "Invariant B", "category": "structural"},
                ]
            }
        )
        provider = _ScriptedProvider({"MODULE :": enrich_response})

        ModuleGraph._enrich_frozen_specs(graph, plan, provider)

        for inv in graph._specs["M1"].invariants:
            assert inv.verified is False, (
                f"Invariant llm-generated ne doit JAMAIS être verified=True : {inv.description!r}"
            )

    def test_module_failure_keeps_skeletal_and_reports_failure(self) -> None:
        """Si le LLM échoue pour un module, on garde le squelettique."""
        modules = [_make_module("M1", "Auth", "authentifier")]
        graph, plan = _build_graph_with_skeletal(modules)

        provider = _ScriptedProvider({})  # Aucun script → AssertionError

        stats = ModuleGraph._enrich_frozen_specs(graph, plan, provider)

        frozen = graph._specs["M1"]
        assert stats["modules_enriched"] == 0
        assert stats["invariants_generated"] == 0
        assert stats["modules_failed"] == ["M1"]
        # Squelletique conservé tel quel.
        assert len(frozen.invariants) == 1
        assert frozen.invariants[0].source == "auto-from-planning"

    def test_empty_llm_response_keeps_skeletal(self) -> None:
        """Si le LLM retourne un objet sans invariants, on garde le squelettique."""
        modules = [_make_module("M1", "Auth", "authentifier")]
        graph, plan = _build_graph_with_skeletal(modules)

        provider = _ScriptedProvider({"MODULE :": json.dumps({"invariants": []})})

        stats = ModuleGraph._enrich_frozen_specs(graph, plan, provider)

        frozen = graph._specs["M1"]
        assert stats["modules_enriched"] == 0
        assert stats["modules_failed"] == ["M1"]
        assert len(frozen.invariants) == 1
        assert frozen.invariants[0].source == "auto-from-planning"

    def test_invalid_category_falls_back_to_functional(self) -> None:
        """Une catégorie inconnue retombe sur 'functional'."""
        modules = [_make_module("M1", "Auth", "authentifier")]
        graph, plan = _build_graph_with_skeletal(modules)

        enrich_response = json.dumps(
            {
                "invariants": [
                    {"description": "X", "category": "invented"},
                ]
            }
        )
        provider = _ScriptedProvider({"MODULE :": enrich_response})

        ModuleGraph._enrich_frozen_specs(graph, plan, provider)

        new_inv = graph._specs["M1"].invariants[1]
        assert new_inv.category == "functional"
        assert new_inv.source == "llm-generated"


# ── Tests CLI ────────────────────────────────────────────────────


class TestCLIEnrichFlag:
    def test_cli_enrich_flag_shows_summary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--enrich-frozen-specs déclenche l'enrichissement et affiche le résumé."""
        # Fichier spec
        spec_path = tmp_path / "spec.md"
        spec_path.write_text(
            "Construire une API d'authentification avec gestion de tokens.",
            encoding="utf-8",
        )

        # Mock provider : plan + enrichissement
        plan_response = json.dumps(
            {
                "modules": [
                    {
                        "id": "M1",
                        "name": "Auth",
                        "responsibility": "authentifier les utilisateurs",
                        "estimated_lines": 500,
                    }
                ],
                "contracts": [],
            }
        )
        enrich_response = json.dumps(
            {
                "invariants": [
                    {"description": "Token absent → 401", "category": "functional"},
                    {"description": "Token expiré → 401", "category": "functional"},
                ]
            }
        )

        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.call.side_effect = lambda prompt, role, tier: (
            LLMResponse(text=plan_response, provider="mock", model="test-medium")
            if "SPÉCIFICATION" in prompt
            else LLMResponse(text=enrich_response, provider="mock", model="test-medium")
        )

        monkeypatch.setattr("goal_cascade.cli._build_provider", lambda *a, **kw: mock_provider)
        monkeypatch.setattr("goal_cascade.cli.DEFAULT_CONFIG_PATH", tmp_path / "absent.toml")

        output_path = tmp_path / "plan.json"
        result = CliRunner().invoke(
            app,
            [
                "plan",
                str(spec_path),
                "--enrich-frozen-specs",
                "--output",
                str(output_path),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Enrichissement LLM" in result.output
        assert "Modules enrichis" in result.output
        assert "verified=False" in result.output
        assert "validez" in result.output.lower()

        # Le plan.json contient l'invariant enrichi.
        saved = json.loads(output_path.read_text(encoding="utf-8"))
        # Au moins un module avec invariants >= 3 (1 squelettique + 2 llm).
        graph_modules = saved["_graph"]["modules"]
        assert len(graph_modules) == 1
        assert len(graph_modules[0]["spec"]["invariants"]) == 3
