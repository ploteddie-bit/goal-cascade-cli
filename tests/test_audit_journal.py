from __future__ import annotations

import hashlib
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from goal_cascade.audit_journal import AuditJournal, redact_sensitive
from goal_cascade.orchestrator import state_manager
from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
from goal_cascade.orchestrator.synthesizer import SynthesisError
from goal_cascade.providers.base import BaseProvider, LLMResponse
from goal_cascade.rag_bridge import (
    IA_GENERAL_EMBED_URL,
    IA_GENERAL_HOST,
    RagBridge,
    RagSyncError,
)
from goal_cascade.schemas.models import Variant


class AuditProvider(BaseProvider):
    def __init__(self, fail: bool = False):
        self.fail = fail

    @property
    def name(self) -> str:
        return "audit-test"

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        if self.fail:
            raise RuntimeError("provider_error token=secret-a-ne-pas-conserver")
        if role == "synthesizer":
            text = json.dumps(
                {
                    "objective": "Objectif audité",
                    "key_decisions": ["Conserver toutes les étapes"],
                    "uncertainties": [],
                    "next_instruction": "Continuer",
                },
                ensure_ascii=False,
            )
        elif role == "arbiter":
            text = (
                "Résultat final\n"
                '{"decision":"STOP","justification":"Audit complet."}'
            )
        else:
            text = f"Sortie visible du rôle {role}"
        return LLMResponse(text=text, provider=self.name, model=f"test-{tier}")


class InvalidSynthesisProvider(AuditProvider):
    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        if role == "synthesizer":
            return LLMResponse(
                text="réponse brute non JSON à conserver",
                provider=self.name,
                model=f"test-{tier}",
            )
        return super().call(prompt, role, tier)


def test_redaction_removes_common_secrets() -> None:
    value = """api_key=abc123 token: xyz789 Authorization: Bearer qwerty
"api_key": "json-secret-123"
OPENAI_API_KEY=env-secret-123
AWS_SECRET_ACCESS_KEY=aws-secret-123
-----BEGIN PRIVATE KEY-----
private-secret-material
-----END PRIVATE KEY-----
"""

    redacted = redact_sensitive(value)

    assert "abc123" not in redacted
    assert "xyz789" not in redacted
    assert "qwerty" not in redacted
    assert "json-secret-123" not in redacted
    assert "env-secret-123" not in redacted
    assert "aws-secret-123" not in redacted
    assert "private-secret-material" not in redacted
    assert "[MASQUÉ]" in redacted


def test_journal_is_permanent_readable_and_sequential(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("run-test")

    prompt_path = journal.save_text(
        "prompt",
        "Question utile\npassword=ne-doit-pas-sortir",
        iteration=1,
        role="producer",
    )
    journal.record_event("appel_termine", iteration=1, role="producer")
    journal.record_error(RuntimeError("api_key=secret-erreur"))
    timeline_path = journal.finalize(
        {
            "objective": "Prouver le cheminement",
            "status": "failed",
            "provider": "audit-test",
        }
    )

    assert prompt_path.exists()
    assert timeline_path.exists()
    events = [
        json.loads(line)
        for line in (journal.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    all_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in journal.run_dir.iterdir()
        if path.is_file()
    )
    assert "ne-doit-pas-sortir" not in all_text
    assert "secret-erreur" not in all_text
    assert "Question utile" in all_text
    assert "appel_termine" in all_text


def test_executor_records_all_prompts_outputs_and_terminal_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    executor = CascadeExecutor(
        provider=AuditProvider(),
        synthesizer_provider=AuditProvider(),
    )

    state = executor.run(
        executor.init_state("Objectif audité", Variant.A),
        verbose=False,
    )

    run_dir = state_manager.RUNS_DIR / state.run_id
    assert state.status == "stopped"
    assert len(list(run_dir.glob("prompt_*.txt"))) == 7
    assert len(list(run_dir.glob("iteration_*.txt"))) == 4
    assert len(list(run_dir.glob("synthesis_*.json"))) == 3
    timeline = (run_dir / "timeline.md").read_text(encoding="utf-8")
    assert "Sortie visible du rôle producer" in timeline
    assert "Résultat final" in timeline
    rag_status = json.loads((run_dir / "rag-status.json").read_text(encoding="utf-8"))
    assert rag_status["status"] == "pending"


def test_executor_persists_provider_error_before_raising(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    executor = CascadeExecutor(
        provider=AuditProvider(fail=True),
        synthesizer_provider=AuditProvider(),
    )
    state = executor.init_state("Objectif en erreur", Variant.B)

    with pytest.raises(RuntimeError, match="provider_error"):
        executor.run(state, verbose=False)

    run_dir = state_manager.RUNS_DIR / state.run_id
    persisted = state_manager.load_state(state.run_id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert (run_dir / "timeline.md").exists()
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.iterdir()
        if path.is_file()
    )
    assert "provider_error" in combined
    assert "secret-a-ne-pas-conserver" not in combined


def test_invalid_synthesis_response_is_persisted_before_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    executor = CascadeExecutor(
        provider=AuditProvider(),
        synthesizer_provider=InvalidSynthesisProvider(),
    )
    state = executor.init_state("Conserver une synthèse invalide", Variant.A)

    with pytest.raises(SynthesisError):
        executor.run(state, verbose=False)

    run_dir = state_manager.RUNS_DIR / state.run_id
    synthesis_path = run_dir / "synthesis_1.json"
    assert synthesis_path.exists()
    assert "réponse brute non JSON" in synthesis_path.read_text(encoding="utf-8")
    timeline = (run_dir / "timeline.md").read_text(encoding="utf-8")
    assert "réponse brute non JSON" in timeline
    assert "SynthesisError" in timeline


def test_rag_bridge_records_embedding_proof(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("rag-ok")
    journal.record_event("run_started", objective="preuve vectorielle")
    journal.finalize({"status": "stopped"})
    worker = tmp_path / "goal-run-ingest.py"
    worker.write_text("# worker de test", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.write_text("", encoding="utf-8")
    captured = {}

    def runner(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        timeline = Path(command[command.index("--timeline") + 1])
        payload = {
            "status": "embedded",
            "document_id": 4242,
            "chunks": 6,
            "dimensions": 1024,
            "model": "bge-m3:latest",
            "endpoint": IA_GENERAL_EMBED_URL,
            "cosine_similarity": 1.0,
            "sha256": hashlib.sha256(timeline.read_bytes()).hexdigest(),
            "source": ".goal/runs/rag-ok/timeline.md",
            "postgres_indexed": True,
        }
        return CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)

    result = bridge.sync_run("rag-ok", journal=journal)

    assert result["document_id"] == 4242
    status = json.loads(journal.rag_status_path.read_text(encoding="utf-8"))
    assert status["status"] == "embedded"
    assert status["dimensions"] == 1024
    assert status["embedding_host"] == "ia-general"
    assert captured["env"]["OLLAMA_HOST"] == IA_GENERAL_HOST
    assert captured["env"]["OLLAMA_EMBED_URL"] == IA_GENERAL_EMBED_URL


def test_rag_bridge_keeps_failure_visible_and_redacted(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("rag-ko")
    journal.finalize({"status": "failed"})
    worker = tmp_path / "goal-run-ingest.py"
    worker.write_text("# worker de test", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.write_text("", encoding="utf-8")

    def runner(command, **kwargs):
        return CompletedProcess(
            command,
            3,
            stdout="",
            stderr="ia-general inaccessible token=secret-rag",
        )

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)

    with pytest.raises(RagSyncError, match="ia-general inaccessible"):
        bridge.sync_run("rag-ko", journal=journal)

    status_text = journal.rag_status_path.read_text(encoding="utf-8")
    assert '"status": "failed"' in status_text
    assert "secret-rag" not in status_text
    assert "ia-general inaccessible" in status_text


def test_rag_bridge_distinguishes_postgres_index_from_pending_embedding(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("rag-pending")
    journal.finalize({"status": "stopped"})
    worker = tmp_path / "goal-run-ingest.py"
    worker.write_text("# worker de test", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.write_text("", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "--index-only" in command:
            timeline = Path(command[command.index("--timeline") + 1])
            payload = {
                "status": "indexed_pending_embedding",
                "document_id": 5150,
                "postgres_indexed": True,
                "sha256": hashlib.sha256(timeline.read_bytes()).hexdigest(),
                "source": ".goal/runs/rag-pending/timeline.md",
            }
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps(payload),
                stderr="",
            )
        payload = {
            "status": "indexed_pending_embedding",
            "message": "ia-general hors ligne",
            "document_id": 5150,
            "postgres_indexed": True,
        }
        return CompletedProcess(
            command,
            1,
            stdout="",
            stderr=json.dumps(payload),
        )

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)

    with pytest.raises(RagSyncError, match="ia-general hors ligne"):
        bridge.sync_run("rag-pending", journal=journal)

    status = json.loads(journal.rag_status_path.read_text(encoding="utf-8"))
    assert status["status"] == "indexed_pending_embedding"
    assert status["postgres_indexed"] is True
    assert status["document_id"] == 5150
    assert len(calls) == 2
    assert "--index-only" in calls[1]


def test_incomplete_embedded_receipt_is_rejected_and_terminalized(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("rag-invalid")
    journal.finalize({"status": "stopped"})
    worker = tmp_path / "goal-run-ingest.py"
    worker.write_text("# worker de test", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.write_text("", encoding="utf-8")
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "--index-only" in command:
            timeline = Path(command[command.index("--timeline") + 1])
            payload = {
                "status": "indexed_pending_embedding",
                "document_id": 6160,
                "postgres_indexed": True,
                "sha256": hashlib.sha256(timeline.read_bytes()).hexdigest(),
                "source": ".goal/runs/rag-invalid/timeline.md",
            }
            return CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")
        return CompletedProcess(
            command,
            0,
            stdout=json.dumps({"status": "embedded"}),
            stderr="",
        )

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)

    with pytest.raises(RagSyncError, match="Reçu embedded invalide"):
        bridge.sync_run("rag-invalid", journal=journal)

    status = json.loads(journal.rag_status_path.read_text(encoding="utf-8"))
    assert status["status"] == "indexed_pending_embedding"
    assert status["status"] != "indexing"
    assert status["document_id"] == 6160
    assert len(calls) == 2


def test_false_embedded_index_only_receipt_and_wrong_hash_are_rejected(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("rag-forged")
    journal.finalize({"status": "stopped"})
    worker = tmp_path / "goal-run-ingest.py"
    worker.write_text("# worker de test", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.write_text("", encoding="utf-8")

    def runner(command, **kwargs):
        if "--index-only" in command:
            forged = {
                "status": "embedded",
                "document_id": 7000,
                "postgres_indexed": True,
                "sha256": "f" * 64,
                "source": ".goal/runs/rag-forged/timeline.md",
            }
            return CompletedProcess(command, 0, stdout=json.dumps(forged), stderr="")
        forged = {
            "status": "embedded",
            "document_id": 7000,
            "chunks": 1,
            "dimensions": 1024,
            "model": "bge-m3:latest",
            "endpoint": IA_GENERAL_EMBED_URL,
            "cosine_similarity": 1.0,
            "postgres_indexed": True,
            "sha256": "f" * 64,
            "source": ".goal/runs/rag-forged/timeline.md",
        }
        return CompletedProcess(command, 0, stdout=json.dumps(forged), stderr="")

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)

    with pytest.raises(RagSyncError, match="sha256"):
        bridge.sync_run("rag-forged", journal=journal)

    status = json.loads(journal.rag_status_path.read_text(encoding="utf-8"))
    assert status["status"] == "failed"
    assert status["status"] != "embedded"
