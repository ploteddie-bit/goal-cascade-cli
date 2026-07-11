from __future__ import annotations

import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from goal_cascade.providers.kimi_command import (
    KimiBackend,
    KimiCommandProvider,
    ProviderCommandError,
)


def test_extracts_legacy_stream_json_text() -> None:
    payload = {
        "role": "assistant",
        "content": [
            {"type": "think", "think": "raisonnement"},
            {"type": "text", "text": "LEGACY_OK"},
        ],
    }
    output = json.dumps(payload) + "\nTo resume this session: kimi -r abc\n"

    assert KimiCommandProvider.extract_assistant_text(output) == "LEGACY_OK"


def test_extracts_kimi_code_stream_json_text() -> None:
    assistant = json.dumps({"role": "assistant", "content": "CODE_OK"})
    meta = json.dumps({"role": "meta", "type": "session.resume_hint"})

    assert KimiCommandProvider.extract_assistant_text(f"{assistant}\n{meta}\n") == "CODE_OK"


@pytest.mark.parametrize("backend", [KimiBackend.CLI, KimiBackend.CODE])
def test_each_call_starts_a_new_noninteractive_session(monkeypatch, backend) -> None:
    captured: list[tuple[list[str], dict]] = []

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        payload = json.dumps({"role": "assistant", "content": "OK"})
        return CompletedProcess(command, 0, stdout=payload, stderr="")

    monkeypatch.setattr("goal_cascade.providers.kimi_command.subprocess.run", fake_run)
    provider = KimiCommandProvider(
        backend=backend,
        model="ia-general/qwen25-14b-1m-q4km",
    )

    response = provider.call("prompt", role="critic")

    assert response.text == "OK"
    assert response.token_count_estimated is True
    command, run_kwargs = captured[0]
    assert "-S" not in command
    assert "--session" not in command
    assert "--continue" not in command
    assert "-C" not in command
    assert "-p" in command
    assert "stream-json" in command
    assert "--model" in command
    assert command[command.index("--model") + 1] == "ia-general/qwen25-14b-1m-q4km"
    assert Path(run_kwargs["cwd"]).name.startswith("goal-kimi-")
    prompt = command[command.index("-p") + 1]
    assert "N'utilise aucun outil" in prompt
    assert "ne modifies et ne supprimes aucun fichier" in prompt
    assert response.model == "ia-general/qwen25-14b-1m-q4km"


def test_nonzero_command_is_reported(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return CompletedProcess(command, 1, stdout="", stderr="provider.connection_error")

    monkeypatch.setattr("goal_cascade.providers.kimi_command.subprocess.run", fake_run)
    provider = KimiCommandProvider(backend=KimiBackend.CODE)

    with pytest.raises(ProviderCommandError, match="provider.connection_error"):
        provider.call("prompt", role="producer")


@pytest.mark.parametrize("model", [None, "", "   "])
def test_synthesizer_call_requires_explicit_nonempty_model(model) -> None:
    provider = KimiCommandProvider(backend=KimiBackend.CODE, model=model)

    with pytest.raises(ProviderCommandError, match="modèle.*synthèse"):
        provider.call("prompt", role="synthesizer", tier="small")
