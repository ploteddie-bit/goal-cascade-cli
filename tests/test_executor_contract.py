from __future__ import annotations

import json

from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.schemas.models import Variant


class RecordingProvider(BaseProvider):
    def __init__(self, arbiter_decision: str = "STOP", with_code: bool = False):
        self.arbiter_decision = arbiter_decision
        self.with_code = with_code
        self.calls: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return "recording"

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        self.calls.append((role, prompt))
        if role == "producer":
            text = "Draft initial"
            if self.with_code:
                text += "\n```python\nprint('preserve-me')\n```"
        elif role == "synthesizer":
            text = json.dumps(
                {
                    "objective": "Objectif de test",
                    "key_decisions": ["Conserver le comportement demandé"],
                    "uncertainties": [],
                    "next_instruction": "Poursuivre avec le rôle suivant",
                },
                ensure_ascii=False,
            )
        elif role == "arbiter":
            text = (
                "Version finale vérifiée.\n"
                f"VERDICT : {self.arbiter_decision}\n"
                "JUSTIFICATION : décision explicite et structurée.\n"
                "Le doute profite au STOP."
            )
        else:
            text = f"Rapport {role}"
        return LLMResponse(text=text, provider=self.name, model=f"test-{tier}")


def test_verdict_parser_uses_explicit_marker() -> None:
    executor = CascadeExecutor(provider=RecordingProvider())
    text = (
        "CONTINUE est défini dans les consignes.\n"
        "VERDICT : CONTINUE\n"
        "JUSTIFICATION : un point précis reste ouvert.\n"
        "Le doute profite au STOP."
    )

    verdict = executor._parse_verdict(text)

    assert verdict.decision == "CONTINUE"
    assert "point précis" in verdict.justification


def test_terminal_forced_stop_is_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    provider = RecordingProvider(arbiter_decision="CONTINUE")
    executor = CascadeExecutor(provider=provider)
    state = executor.init_state("Tester la limite", Variant.A)

    result = executor.run(state, verbose=False)
    reloaded = state_manager.load_state(result.run_id)

    assert result.status == "forced_stop"
    assert reloaded is not None
    assert reloaded.status == "forced_stop"
    assert reloaded.final_verdict is not None
    assert reloaded.final_verdict.decision == "STOP"


def test_synthesis_runs_in_fresh_provider_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    provider = RecordingProvider()
    executor = CascadeExecutor(provider=provider)

    state = executor.run(
        executor.init_state("Objectif de test", Variant.A),
        verbose=False,
    )

    roles = [role for role, _ in provider.calls]
    assert roles == [
        "producer",
        "synthesizer",
        "critic",
        "synthesizer",
        "adversary",
        "synthesizer",
        "arbiter",
    ]
    assert state.last_synthesis is not None
    critic_prompt = next(prompt for role, prompt in provider.calls if role == "critic")
    assert "Conserver le comportement demandé" in critic_prompt
    assert "Draft initial" not in critic_prompt


def test_technical_artifact_is_preserved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    provider = RecordingProvider(with_code=True)
    executor = CascadeExecutor(provider=provider)

    state = executor.run(
        executor.init_state("Produire un script", Variant.B),
        verbose=False,
    )

    assert any("preserve-me" in artifact.content for artifact in state.artifacts)
    critic_prompt = next(prompt for role, prompt in provider.calls if role == "critic")
    assert "print('preserve-me')" in critic_prompt

