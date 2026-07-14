"""Tests du câblage CICDHook dans la cascade unique (cascade_executor).

Vérifie que :
- CICDHook est bien appelé après chaque synthèse.
- Un artefact Python cassé est détecté.
- Un échec CICD ne bloque PAS la cascade (artefacts préservés).
- Le hook est tracé dans le journal d'audit.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.schemas.models import Variant


class _ArtifactProducingProvider(BaseProvider):
    """Provider qui produit un artefact (code cassé ou valide) à l'itération 1."""

    def __init__(self, code_block: str | None = None) -> None:
        self._code_block = code_block
        self._name = "artifact-provider"

    @property
    def name(self) -> str:
        return self._name

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        if role == "producer":
            text = "Draft initial du livrable"
            if self._code_block is not None:
                text += f"\n\n```python\n{self._code_block}\n```"
        elif role == "synthesizer":
            text = json.dumps(
                {
                    "objective": "Objectif de test",
                    "key_decisions": ["Préserver l'artefact produit"],
                    "uncertainties": [],
                    "next_instruction": "Poursuivre",
                },
                ensure_ascii=False,
            )
        elif role == "arbiter":
            text = (
                "Version finale.\n```json\n"
                + json.dumps(
                    {
                        "decision": "STOP",
                        "justification": "Test OK",
                    },
                    ensure_ascii=False,
                )
                + "\n```"
            )
        else:
            text = f"Rapport {role}"
        return LLMResponse(text=text, provider=self._name, model=f"test-{tier}")


def _make_executor(provider: BaseProvider) -> CascadeExecutor:
    return CascadeExecutor(
        provider=provider,
        synthesizer_provider=_ArtifactProducingProvider(),
    )


class TestCICDHookWiring:
    def test_cicd_hook_is_called_after_synthesis(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CICDHook est invoqué après chaque synthèse et tracé dans le journal."""
        monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")

        executor = _make_executor(_ArtifactProducingProvider(code_block="x = 1\n"))
        spy_hook = MagicMock()
        spy_hook.run_deterministic_checks.return_value.passed = True
        spy_hook.run_deterministic_checks.return_value.failures = []
        executor._cicd = spy_hook

        state = executor.run(
            executor.init_state("Test câblage", Variant.A),
            verbose=False,
        )

        # Au moins un appel CICD (après chaque synthèse non-arbitre).
        assert spy_hook.run_deterministic_checks.call_count >= 1
        # Le premier argument est un InterfaceContract interne.
        first_call = spy_hook.run_deterministic_checks.call_args_list[0]
        contract = first_call.args[0]
        assert contract.contract_id.startswith("cicd-")
        assert contract.producer_module == "cascade"

        # Vérifie qu'au moins un appel CICD est tracé dans le journal.
        journal_path = tmp_path / "runs" / state.run_id / "events.jsonl"
        events = journal_path.read_text(encoding="utf-8").splitlines()
        cicd_events = [
            json.loads(line) for line in events if json.loads(line).get("event") == "cicd_checks"
        ]
        assert len(cicd_events) >= 1

    def test_cicd_detects_invalid_python_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un artefact Python cassé est détecté par le hook déterministe."""
        monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")

        # Python avec une SyntaxError volontaire.
        executor = _make_executor(
            _ArtifactProducingProvider(code_block="def broken(:\n    pass\n"),
        )

        state = executor.run(
            executor.init_state("Test artefact cassé", Variant.A),
            verbose=False,
        )

        # La cascade continue malgré l'échec (non bloquant).
        assert state.status == "stopped"

        # Le journal doit tracer l'échec CICD.
        journal_path = tmp_path / "runs" / state.run_id / "events.jsonl"
        events = journal_path.read_text(encoding="utf-8").splitlines()
        cicd_failures = [
            json.loads(line)
            for line in events
            if json.loads(line).get("event") == "cicd_checks"
            and json.loads(line).get("passed") is False
        ]
        assert len(cicd_failures) >= 1
        # L'artefact cassé est tout de même préservé dans state.artifacts.
        assert any("def broken" in art.content for art in state.artifacts)

    def test_cicd_does_not_block_cascade(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un échec CICD n'arrête PAS la cascade (mode informatif)."""
        monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")

        executor = _make_executor(
            _ArtifactProducingProvider(code_block="def broken(:\n"),
        )

        state = executor.run(
            executor.init_state("Test non-bloquant", Variant.A),
            verbose=False,
        )

        # Cascade terminée normalement.
        assert state.status in ("stopped", "forced_stop")
        assert state.final_verdict is not None
        assert state.final_verdict.decision == "STOP"
