"""Journal d'audit permanent et lisible pour une cascade G.O.A.L."""

from __future__ import annotations

import hashlib
import json
import re
import traceback
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .orchestrator import state_manager

SECRET_KEY = (
    r"[A-Z0-9_-]*(?:API[_-]?KEY|SECRET[_-]?ACCESS[_-]?KEY|"
    r"ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|PASSWORD|PASSWD|"
    r"PRIVATE[_-]?KEY|TOKEN|SECRET)"
)
QUOTED_SECRET_RE = re.compile(
    rf"(?P<prefix>[\"']?{SECRET_KEY}[\"']?\s*[:=]\s*)"
    rf"(?P<quote>[\"'])(?P<value>.*?)(?P=quote)",
    re.IGNORECASE,
)
UNQUOTED_SECRET_RE = re.compile(
    rf"(?P<prefix>\b{SECRET_KEY}\b\s*[:=]\s*)"
    rf"(?P<value>(?!\[MASQUÉ\])[^\s,;]+)",
    re.IGNORECASE,
)
AUTHORIZATION_RE = re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+[^\s,;]+")
PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----.*?"
    r"-----END(?: [A-Z0-9]+)* PRIVATE KEY-----",
    re.DOTALL,
)
OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


def redact_sensitive(value: str) -> str:
    """Masque les formes usuelles de secrets avant toute persistance."""
    result = PRIVATE_KEY_RE.sub("[CLÉ PRIVÉE MASQUÉE]", value)
    result = AUTHORIZATION_RE.sub("Authorization: Bearer [MASQUÉ]", result)
    result = QUOTED_SECRET_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}[MASQUÉ]{match.group('quote')}"
        ),
        result,
    )
    result = UNQUOTED_SECRET_RE.sub(
        lambda match: f"{match.group('prefix')}[MASQUÉ]",
        result,
    )
    result = OPENAI_KEY_RE.sub("[MASQUÉ]", result)
    return result


def _redact_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive(value)
    if isinstance(value, dict):
        return {str(key): _redact_data(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_data(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class AuditJournal:
    """Écrit les événements et artefacts sans dépendre du service RAG."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.run_dir = state_manager.get_run_dir(run_id)
        self.events_path = self.run_dir / "events.jsonl"
        self.timeline_path = self.run_dir / "timeline.md"
        self.rag_status_path = self.run_dir / "rag-status.json"
        self.metadata_path = self.run_dir / "run-metadata.json"
        self._sequence = self._last_sequence()

    def _last_sequence(self) -> int:
        if not self.events_path.exists():
            return 0
        for line in reversed(self.events_path.read_text(encoding="utf-8").splitlines()):
            try:
                return int(json.loads(line).get("sequence", 0))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return 0

    def record_event(self, event_type: str, **data: Any) -> dict[str, Any]:
        """Ajoute un événement append-only, horodaté, numéroté et hashé.

        Concurrence (issue #3) :
        - ``fcntl.flock`` sur events_path.fileno() pour garantir
          qu'un seul processus écrit à la fois (évite interleaving).
        - Le compteur ``_sequence`` reste en mémoire ; on le relit depuis
          events.jsonl au démarrage (méthode ``_last_sequence``). Si deux
          processus écrivent en même temps, le flock les sérialise.

        Tamper-evidence (issue #3) :
        - Chaque event inclut ``prev_event_hash`` (sha256 de l'event précédent
          dans la chaîne, ou chaîne vide pour le premier).
        - Chaque event inclut ``event_hash`` (sha256 de son propre contenu
          + prev_event_hash). Toute modification d'un event passé casse
          la chaîne (les event_hash suivants ne correspondent plus).
        """
        # 1) Récupérer la dernière ligne (= dernier event) pour le chaînage.
        #    On le fait AVANT de prendre le lock pour minimiser la fenêtre.
        prev_event_hash = self._last_event_hash()

        # 2) Incrémenter la séquence et construire l'event SANS le hash.
        self._sequence += 1
        event_sans_hash = {
            "sequence": self._sequence,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "event": event_type,
            "prev_event_hash": prev_event_hash,
            **_redact_data(data),
        }

        # 3) Calculer le hash SUR le contenu SANS le champ event_hash.
        #    Le hash est ainsi DÉTERMINISTE : il représente exactement
        #    le contenu sérialisé (sans le champ qu'on est en train
        #    de calculer). La vérification se fait en relisant le journal
        #    et en recalculant sha256(json(sans event_hash) + prev_event_hash).
        sans_hash_str = json.dumps(
            event_sans_hash, ensure_ascii=False, sort_keys=True
        )
        event_hash = hashlib.sha256(
            (sans_hash_str + prev_event_hash).encode("utf-8")
        ).hexdigest()
        event_sans_hash["event_hash"] = event_hash

        # 4) Sérialisation FINALE (avec event_hash inclus) — c'est la
        #    chaîne qui sera écrite sur disque.
        final_str = json.dumps(
            event_sans_hash, ensure_ascii=False, sort_keys=True
        )

        # 5) Écriture atomique (lock + append). Le hash INSÉRÉ dans la
        #    ligne est le HASH DU CONTENU SANS event_hash, pas de la
        #    ligne finale — ce qui garantit la cohérence déterministe.
        with open(self.events_path, "a", encoding="utf-8") as stream:
            try:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                # Windows ou fs sans flock : best-effort sans lock.
                # Le compteur _sequence reste vulnérable aux races.
                pass
            try:
                stream.write(final_str + "\n")
            finally:
                try:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                except (NameError, OSError):
                    pass

        return event_sans_hash

    def _last_event_hash(self) -> str:
        """Lit le dernier event_hash du journal (ou chaîne vide si vide)."""
        if not self.events_path.exists():
            return ""
        last_hash = ""
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
                last_hash = ev.get("event_hash", last_hash)
            except json.JSONDecodeError:
                continue
        return last_hash

    def save_text(
        self,
        kind: str,
        content: str,
        *,
        iteration: int,
        role: str,
        suffix: str = ".txt",
    ) -> Path:
        """Persiste un prompt ou une sortie et journalise son empreinte."""
        safe_content = redact_sensitive(content)
        if kind == "prompt":
            filename = f"prompt_{iteration}_{role}{suffix}"
        else:
            filename = f"{kind}_{iteration}_{role}{suffix}"
        path = self.run_dir / filename
        path.write_text(safe_content, encoding="utf-8")
        digest = hashlib.sha256(safe_content.encode("utf-8")).hexdigest()
        self.record_event(
            f"{kind}_saved",
            iteration=iteration,
            role=role,
            path=str(path),
            sha256=digest,
            bytes=len(safe_content.encode("utf-8")),
        )
        return path

    def record_file(
        self,
        event_type: str,
        path: Path,
        *,
        iteration: int | None = None,
        role: str | None = None,
    ) -> None:
        content = path.read_text(encoding="utf-8")
        self.record_event(
            event_type,
            iteration=iteration,
            role=role,
            path=str(path),
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            bytes=len(content.encode("utf-8")),
        )

    def record_error(self, error: BaseException) -> None:
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        self.record_event(
            "error",
            error_type=type(error).__name__,
            message=redact_sensitive(str(error)),
            traceback=redact_sensitive(trace),
        )

    def update_rag_status(self, status: str, **details: Any) -> Path:
        payload = {
            "run_id": self.run_id,
            "status": status,
            "updated_at_utc": datetime.now(UTC).isoformat(),
            **_redact_data(details),
        }
        self.rag_status_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return self.rag_status_path

    def finalize(self, metadata: dict[str, Any]) -> Path:
        """Génère le manifeste humain qui sera l'unique document RAG du run."""
        safe_metadata = _redact_data(metadata)
        self.metadata_path.write_text(
            json.dumps(safe_metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self.record_event("run_finished", **safe_metadata)
        if not self.rag_status_path.exists():
            self.update_rag_status(
                "pending",
                message="En attente d'indexation et d'embedding par ia-general",
                embedding_host="ia-general",
                embedding_model="bge-m3:latest",
            )

        return self._render_timeline(safe_metadata)

    def refresh_timeline(self) -> Path:
        """Reconstruit le manifeste après un événement RAG ou une erreur."""
        metadata: dict[str, Any] = {}
        if self.metadata_path.exists():
            metadata = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        return self._render_timeline(metadata)

    def _render_timeline(self, safe_metadata: dict[str, Any]) -> Path:
        events = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        lines = [
            f"# Traçabilité G.O.A.L. — run {self.run_id}",
            "",
            "## Résumé",
            "",
        ]
        for key, value in safe_metadata.items():
            lines.append(f"- {key}: {value}")

        lines.extend(["", "## Événements", ""])
        artifact_paths: list[Path] = []
        for event in events:
            lines.append(
                f"### {event.get('sequence')} — {event.get('event')} ({event.get('timestamp_utc')})"
            )
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(event, ensure_ascii=False, indent=2, sort_keys=True))
            lines.append("```")
            lines.append("")
            raw_path = event.get("path")
            if raw_path:
                path = Path(raw_path)
                if path.exists() and path.is_file() and path not in artifact_paths:
                    artifact_paths.append(path)

        lines.extend(["## Données persistées", ""])
        for path in artifact_paths:
            content = redact_sensitive(path.read_text(encoding="utf-8"))
            lines.extend(
                [
                    f"### {path.name}",
                    "",
                    f"Chemin : `{path}`",
                    "",
                    "```text",
                    content,
                    "```",
                    "",
                ]
            )

        self.timeline_path.write_text("\n".join(lines), encoding="utf-8")
        return self.timeline_path
