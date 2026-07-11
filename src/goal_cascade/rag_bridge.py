"""Pont durable entre les traces G.O.A.L. et le RAG PostgreSQL local."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable

from .audit_journal import AuditJournal, redact_sensitive


IA_GENERAL_HOST = "http://localhost:11434"
IA_GENERAL_EMBED_URL = f"{IA_GENERAL_HOST}/api/embed"


class RagSyncError(RuntimeError):
    """La trace reste locale, mais sa synchronisation RAG a échoué."""


class RagBridge:
    """Appelle le worker RAG avec le Python qui possède déjà psycopg2."""

    def __init__(
        self,
        worker_path: Path | None = None,
        interpreter: Path | None = None,
        runner: Callable = subprocess.run,
        timeout_s: int = 900,
    ):
        rag_dir = Path.home() / ".kimi" / "kimi-rag"
        self.worker_path = worker_path or rag_dir / "goal-run-ingest.py"
        self.interpreter = interpreter or rag_dir / "venv" / "bin" / "python"
        self.runner = runner
        self.timeout_s = timeout_s

    def sync_run(
        self,
        run_id: str,
        *,
        journal: AuditJournal | None = None,
    ) -> dict:
        journal = journal or AuditJournal(run_id)
        if not journal.timeline_path.exists():
            raise RagSyncError(f"Manifeste absent : {journal.timeline_path}")
        if not self.interpreter.exists():
            raise RagSyncError(f"Interpréteur RAG absent : {self.interpreter}")
        if not self.worker_path.exists():
            raise RagSyncError(f"Worker RAG absent : {self.worker_path}")

        journal.record_event(
            "rag_sync_started",
            embedding_host="ia-general",
            embedding_model="bge-m3:latest",
            timeline=str(journal.timeline_path),
        )
        journal.update_rag_status(
            "indexing",
            message="Synchronisation PostgreSQL et embedding en cours",
            embedding_host="ia-general",
            embedding_model="bge-m3:latest",
        )
        journal.refresh_timeline()

        command = [
            str(self.interpreter),
            str(self.worker_path),
            "--timeline",
            str(journal.timeline_path),
            "--run-id",
            run_id,
        ]
        env = os.environ.copy()
        env["OLLAMA_HOST"] = IA_GENERAL_HOST
        env["OLLAMA_EMBED_URL"] = IA_GENERAL_EMBED_URL
        env["OLLAMA_EMBED_MODEL"] = "bge-m3:latest"

        try:
            completed = self.runner(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            message = redact_sensitive(str(exc))
            journal.record_event("rag_sync_failed", message=message)
            journal.update_rag_status("failed", message=message)
            journal.refresh_timeline()
            raise RagSyncError(message) from exc

        if completed.returncode != 0:
            raw_error = completed.stderr or completed.stdout or "Erreur RAG inconnue"
            failure = self._parse_failure(raw_error)
            failure_status = failure.pop("status", "failed")
            if failure_status not in {"failed", "indexed_pending_embedding"}:
                failure_status = "failed"
            message = redact_sensitive(str(failure.pop("message", raw_error.strip())))
            journal.record_event(
                "rag_sync_failed",
                returncode=completed.returncode,
                message=message,
                **failure,
            )
            journal.update_rag_status(
                failure_status,
                returncode=completed.returncode,
                message=message,
                embedding_host="ia-general",
                embedding_model="bge-m3:latest",
                **failure,
            )
            journal.refresh_timeline()
            index_receipt = self._index_only(
                command, env, journal.timeline_path, run_id
            )
            if index_receipt:
                receipt_status = index_receipt.pop(
                    "status", "indexed_pending_embedding"
                )
                combined_receipt = {**failure, **index_receipt}
                journal.update_rag_status(
                    receipt_status,
                    returncode=completed.returncode,
                    message=message,
                    embedding_host="ia-general",
                    embedding_model="bge-m3:latest",
                    **combined_receipt,
                )
            raise RagSyncError(message)

        try:
            result = self._parse_result(
                completed.stdout, run_id, journal.timeline_path
            )
        except RagSyncError as exc:
            message = redact_sensitive(str(exc))
            journal.record_event("rag_receipt_invalid", message=message)
            journal.update_rag_status(
                "failed",
                message=message,
                embedding_host="ia-general",
                embedding_model="bge-m3:latest",
            )
            journal.refresh_timeline()
            index_receipt = self._index_only(
                command, env, journal.timeline_path, run_id
            )
            if index_receipt:
                receipt_status = index_receipt.pop(
                    "status", "indexed_pending_embedding"
                )
                journal.update_rag_status(
                    receipt_status,
                    message=message,
                    embedding_host="ia-general",
                    embedding_model="bge-m3:latest",
                    **index_receipt,
                )
            raise
        receipt = {key: value for key, value in result.items() if key != "status"}
        journal.update_rag_status(
            "embedded",
            message="Document indexé et segments vectoriels vérifiés",
            embedding_host="ia-general",
            **receipt,
        )
        return result

    @staticmethod
    def _parse_result(stdout: str, run_id: str, timeline_path: Path) -> dict:
        expected_sha256 = hashlib.sha256(timeline_path.read_bytes()).hexdigest()
        for line in reversed(stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, dict) or value.get("status") != "embedded":
                continue
            errors = []
            if not isinstance(value.get("document_id"), int) or isinstance(
                value.get("document_id"), bool
            ) or value.get("document_id", 0) <= 0:
                errors.append("document_id")
            if not isinstance(value.get("chunks"), int) or isinstance(
                value.get("chunks"), bool
            ) or value.get("chunks", 0) <= 0:
                errors.append("chunks")
            if value.get("dimensions") != 1024:
                errors.append("dimensions")
            if value.get("model") != "bge-m3:latest":
                errors.append("model")
            if value.get("endpoint") != IA_GENERAL_EMBED_URL:
                errors.append("endpoint")
            similarity = value.get("cosine_similarity")
            if not isinstance(similarity, (int, float)) or isinstance(
                similarity, bool
            ) or not 0.99 <= float(similarity) <= 1.0001:
                errors.append("cosine_similarity")
            if value.get("postgres_indexed") is not True:
                errors.append("postgres_indexed")
            if value.get("sha256") != expected_sha256:
                errors.append("sha256")
            expected_source = f".goal/runs/{run_id}/timeline.md"
            if value.get("source") != expected_source:
                errors.append("source")
            if errors:
                raise RagSyncError(
                    "Reçu embedded invalide : " + ", ".join(errors)
                )
            return value
        raise RagSyncError("Reçu embedded invalide : preuve JSON absente")

    @staticmethod
    def _parse_failure(output: str) -> dict:
        for line in reversed(output.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return {"status": "failed", "message": output.strip()}

    def _index_only(
        self,
        command: list[str],
        env: dict[str, str],
        timeline_path: Path,
        run_id: str,
    ) -> dict | None:
        """Réécrit le manifeste incluant l'erreur, sans rappeler ia-general."""
        try:
            completed = self.runner(
                [*command, "--index-only"],
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        result = self._parse_failure(completed.stdout)
        expected_sha256 = hashlib.sha256(timeline_path.read_bytes()).hexdigest()
        expected_source = f".goal/runs/{run_id}/timeline.md"
        document_id = result.get("document_id")
        if (
            result.get("status") != "indexed_pending_embedding"
            or result.get("postgres_indexed") is not True
            or not isinstance(document_id, int)
            or isinstance(document_id, bool)
            or document_id <= 0
            or result.get("source") != expected_source
            or result.get("sha256") != expected_sha256
        ):
            return None
        return result
