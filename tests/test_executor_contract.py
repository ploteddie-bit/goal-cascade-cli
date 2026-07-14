from __future__ import annotations

import json

from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.schemas.models import ImmutableArtifact, LLMCallRecord, Variant


class RecordingProvider(BaseProvider):
    def __init__(
        self,
        arbiter_decision: str = "STOP",
        with_code: bool = False,
        name: str = "recording",
    ):
        self.arbiter_decision = arbiter_decision
        self.with_code = with_code
        self._name = name
        self.calls: list[tuple[str, str]] = []

    @property
    def name(self) -> str:
        return self._name

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
                "```json\n"
                + json.dumps(
                    {
                        "decision": self.arbiter_decision,
                        "justification": "Décision explicite et structurée.",
                    },
                    ensure_ascii=False,
                )
                + "\n```"
            )
        else:
            text = f"Rapport {role}"
        return LLMResponse(text=text, provider=self.name, model=f"test-{tier}")


def test_verdict_parser_uses_structured_json() -> None:
    executor = CascadeExecutor(
        provider=RecordingProvider(name="main"),
        synthesizer_provider=RecordingProvider(name="small"),
    )
    text = (
        "Livrable final.\n"
        "```json\n"
        '{"decision":"CONTINUE","justification":"Un point précis reste ouvert."}'
        "\n```"
    )

    verdict = executor._parse_verdict(text)

    assert verdict.decision == "CONTINUE"
    assert "point précis" in verdict.justification.lower()


def test_executor_rejects_shared_main_and_synthesizer_provider() -> None:
    provider = RecordingProvider()

    try:
        CascadeExecutor(provider=provider, synthesizer_provider=provider)
    except ValueError as error:
        assert "distincte" in str(error)
    else:
        raise AssertionError("Le provider de synthèse doit rester isolé")


def test_verdict_parser_rejects_legacy_text_marker() -> None:
    executor = CascadeExecutor(
        provider=RecordingProvider(name="main"),
        synthesizer_provider=RecordingProvider(name="small"),
    )

    try:
        executor._parse_verdict("**Verdict** : STOP\nJUSTIFICATION : ancien format non structuré")
    except ValueError as error:
        assert "JSON" in str(error)
    else:
        raise AssertionError("Le format textuel historique ne doit plus être accepté")


def test_verdict_parser_rejects_non_terminal_nested_or_extended_json() -> None:
    executor = CascadeExecutor(
        provider=RecordingProvider(name="main"),
        synthesizer_provider=RecordingProvider(name="small"),
    )
    invalid_responses = [
        '{"decision":"STOP","justification":"ok","extra":"interdit"}',
        '{"wrapper":{"decision":"STOP","justification":"imbriqué"}}',
        '{"decision":"STOP","justification":"ok"}\ntexte après le verdict',
    ]

    for response in invalid_responses:
        try:
            executor._parse_verdict(response)
        except ValueError:
            continue
        raise AssertionError(f"Verdict invalide accepté : {response}")


def test_arbiter_never_receives_raw_history_and_keeps_artifacts() -> None:
    executor = CascadeExecutor(
        provider=RecordingProvider(name="main"),
        synthesizer_provider=RecordingProvider(name="small"),
    )
    state = executor.init_state("Objectif immuable", Variant.A)
    state.history.append(
        LLMCallRecord(
            provider="test",
            model="test",
            iteration=1,
            role="producer",
            raw_output="BROUILLON_BRUT_INTERDIT",
        )
    )
    state.artifacts.append(
        ImmutableArtifact(
            artifact_type="code",
            language="python",
            content="print('artefact-immuable')",
            source_iteration=1,
        )
    )

    prompt = executor._build_prompt(state, state.role_for_iteration(4))

    assert "BROUILLON_BRUT_INTERDIT" not in prompt
    assert "print('artefact-immuable')" in prompt


def test_terminal_forced_stop_is_persisted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    provider = RecordingProvider(arbiter_decision="CONTINUE", name="main")
    executor = CascadeExecutor(
        provider=provider,
        synthesizer_provider=RecordingProvider(name="small"),
    )
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
    provider = RecordingProvider(name="main")
    synthesizer_provider = RecordingProvider(name="small")
    executor = CascadeExecutor(
        provider=provider,
        synthesizer_provider=synthesizer_provider,
    )

    state = executor.run(
        executor.init_state("Objectif de test", Variant.A),
        verbose=False,
    )

    roles = [role for role, _ in provider.calls]
    assert roles == [
        "producer",
        "critic",
        "adversary",
        "arbiter",
    ]
    assert [role for role, _ in synthesizer_provider.calls] == [
        "synthesizer",
        "synthesizer",
        "synthesizer",
    ]
    assert state.last_synthesis is not None
    critic_prompt = next(prompt for role, prompt in provider.calls if role == "critic")
    assert "Conserver le comportement demandé" in critic_prompt
    assert "Draft initial" not in critic_prompt


def test_technical_artifact_is_preserved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    provider = RecordingProvider(with_code=True, name="main")
    executor = CascadeExecutor(
        provider=provider,
        synthesizer_provider=RecordingProvider(name="small"),
    )

    state = executor.run(
        executor.init_state("Produire un script", Variant.B),
        verbose=False,
    )

    assert any("preserve-me" in artifact.content for artifact in state.artifacts)
    critic_prompt = next(prompt for role, prompt in provider.calls if role == "critic")
    assert "print('preserve-me')" in critic_prompt
    arbiter_prompt = next(prompt for role, prompt in provider.calls if role == "arbiter")
    assert "print('preserve-me')" in arbiter_prompt
    assert "Draft initial" not in arbiter_prompt
    assert "Rapport critic" not in arbiter_prompt
    assert "Rapport adversary" not in arbiter_prompt


def test_no_synth_skips_synthesis(tmp_path, monkeypatch) -> None:
    """En mode --no-synth, le synthesizer n'est pas appelé.

    La sortie brute de chaque itération est passée directement à la suivante,
    sans filtre synthèse. Utile pour debugger une synthèse qui écrase des
    informations critiques.
    """
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    provider = RecordingProvider(name="main")
    synthesizer_provider = RecordingProvider(name="small")
    executor = CascadeExecutor(
        provider=provider,
        synthesizer_provider=synthesizer_provider,
    )

    state = executor.run(
        executor.init_state("Objectif de test no_synth", Variant.A),
        verbose=False,
        no_synth=True,
    )

    # Le provider principal fait toujours 4 appels (producer, critic,
    # adversary, arbiter).
    roles = [role for role, _ in provider.calls]
    assert roles == [
        "producer",
        "critic",
        "adversary",
        "arbiter",
    ]

    # Le synthesizer ne fait AUCUN appel en mode --no-synth.
    assert synthesizer_provider.calls == []

    # last_synthesis reste None car la synthèse n'est jamais générée.
    assert state.last_synthesis is None

    # Le prompt du critique contient la sortie brute du producteur
    # (pas de synthèse intermédiaire).
    critic_prompt = next(prompt for role, prompt in provider.calls if role == "critic")
    assert "Draft initial" in critic_prompt or "Producteur" in critic_prompt
