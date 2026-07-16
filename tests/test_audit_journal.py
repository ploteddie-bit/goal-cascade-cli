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
from goal_cascade.rag import default_ollama_embed_url, default_ollama_host
from goal_cascade.rag_bridge import (
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
            text = 'Résultat final\n{"decision":"STOP","justification":"Audit complet."}'
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
        path.read_text(encoding="utf-8") for path in journal.run_dir.iterdir() if path.is_file()
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
        path.read_text(encoding="utf-8") for path in run_dir.iterdir() if path.is_file()
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
            "endpoint": default_ollama_embed_url(),
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
    expected_host = (
        default_ollama_host().replace("http://", "").replace("https://", "").split(":")[0]
    )
    assert status["embedding_host"] == expected_host
    assert captured["env"]["OLLAMA_HOST"] == default_ollama_host()
    assert captured["env"]["OLLAMA_EMBED_URL"] == default_ollama_embed_url()


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


def test_incomplete_embedded_receipt_is_rejected_and_terminalized(tmp_path, monkeypatch) -> None:
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
            "endpoint": default_ollama_embed_url(),
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


def test_rag_bridge_uses_versioned_worker_first(tmp_path) -> None:
    from goal_cascade.rag import resolve_worker_path

    bridge = RagBridge()
    assert resolve_worker_path().exists()
    assert bridge.worker_path == resolve_worker_path()


def test_rag_bridge_propagates_ollama_host(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.1:11434")
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path / "runs")
    journal = AuditJournal("rag-env")
    journal.finalize({"status": "stopped"})
    worker = tmp_path / "worker.py"
    worker.write_text("# worker de test", encoding="utf-8")
    interpreter = tmp_path / "python"
    interpreter.write_text("", encoding="utf-8")
    captured: dict = {}

    def runner(command, **kwargs):
        captured["env"] = kwargs["env"]
        return CompletedProcess(
            command, 1, stdout="", stderr='{"status":"failed","message":"nope"}'
        )

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)
    with pytest.raises(RagSyncError):
        bridge.sync_run("rag-env", journal=journal)
    assert captured["env"]["OLLAMA_HOST"] == "http://10.0.0.1:11434"


# ── #3 — Tamper-evidence (chaînage par hash) ──────────────────────


def test_journal_hash_chain_chaque_event_inclut_prev_hash(
    tmp_path, monkeypatch
) -> None:
    """Chaque event écrit doit inclure prev_event_hash et event_hash.

    La chaîne commence par prev_event_hash="" pour le premier event,
    et chaque event_hash est calculé à partir du contenu + prev_event_hash.
    Modifier n'importe quel event passé casse la chaîne.
    """
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)
    rep = tmp_path / "abc123"
    rep.mkdir(parents=True)
    journal = AuditJournal("abc123")
    journal.finalize({"status": "running"})

    # Émettre 3 events
    journal.record_event("event_a", foo=1)
    journal.record_event("event_b", foo=2)
    journal.record_event("event_c", foo=3)

    # Lire le journal
    events = []
    for line in (rep / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))

    # 4 events attendus : 1 run_finished (du finalize) + 3 manuels
    assert len(events) == 4

    # Chaque event a sequence, event_hash, prev_event_hash
    for ev in events:
        assert "sequence" in ev
        assert "event_hash" in ev
        assert "prev_event_hash" in ev

    # Le 1er event (run_finished du finalize) a prev_event_hash vide
    assert events[0]["prev_event_hash"] == ""

    # Chaque event sauf le 1er a prev_event_hash = event_hash du précédent
    for i in range(1, 4):
        assert events[i]["prev_event_hash"] == events[i - 1]["event_hash"], (
            f"events[{i}].prev_event_hash doit matcher events[{i-1}].event_hash"
        )

    # Les event_hash sont uniques
    hashes = [ev["event_hash"] for ev in events]
    assert len(set(hashes)) == 4

    # Les sequences sont monotones
    seqs = [ev["sequence"] for ev in events]
    assert seqs == [1, 2, 3, 4]


def test_journal_hash_round_trip_recalcul_independent(tmp_path, monkeypatch) -> None:
    """Le hash stocké doit être recalculable indépendamment du contenu du fichier.

    Pour chaque event dans le journal :
    1. Reconstruire le dict SANS le champ event_hash
    2. Sérialiser de manière canonique (mêmes kwargs sort_keys, ensure_ascii)
    3. Calculer sha256(sérialisation + prev_event_hash)
    4. Comparer avec le event_hash stocké → doit matcher exactement

    C'est la garantie de tamper-evidence : n'importe qui peut recalculer
    le hash de manière indépendante et détecter une altération.
    """
    import hashlib
    monkeypatch.setattr(state_manager, "RUNS_DIR", tmp_path)
    rep = tmp_path / "abc123"
    rep.mkdir(parents=True)
    journal = AuditJournal("abc123")
    journal.finalize({"status": "running"})

    # Émettre 5 events pour avoir une chaîne intéressante
    for i in range(5):
        journal.record_event(f"event_{i}", payload=f"data_{i}")

    # Lire chaque ligne et recalculer le hash
    events = []
    for line in (rep / "events.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            ev = json.loads(line)
            events.append(ev)

    for ev in events:
        # 1. Reconstruire le dict SANS event_hash
        ev_sans_hash = {k: v for k, v in ev.items() if k != "event_hash"}

        # 2. Sérialisation canonique (mêmes kwargs que record_event)
        sans_hash_str = json.dumps(
            ev_sans_hash, ensure_ascii=False, sort_keys=True
        )

        # 3. Recalcul du hash
        recalcule = hashlib.sha256(
            (sans_hash_str + ev["prev_event_hash"]).encode("utf-8")
        ).hexdigest()

        # 4. Match avec le hash stocké
        assert recalcule == ev["event_hash"], (
            f"event seq={ev['sequence']} ({ev['event']}): "
            f"hash recalculé {recalcule[:16]}... != stocké {ev['event_hash'][:16]}..."
        )

    # Vérification supplémentaire : prev_event_hash de N+1 == event_hash de N
    for i in range(1, len(events)):
        assert events[i]["prev_event_hash"] == events[i - 1]["event_hash"], (
            f"Cassure de chaîne à l'event {i}"
        )
