#!/usr/bin/env python3
"""Indexation ciblée d'un manifeste G.O.A.L. avec embeddings via Ollama."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2

PACKAGE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE_DIR.parents[1]))

from goal_cascade.rag.embed import OllamaEmbedding  # noqa: E402

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_EMBED_URL = f"{DEFAULT_HOST}/api/embed"
DEFAULT_MODEL = "bge-m3:latest"
MAX_CHUNK_CHARS = 1400
CHUNK_OVERLAP_CHARS = 120
ENV_PATH = PACKAGE_DIR / ".env"

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
    return OPENAI_KEY_RE.sub("[MASQUÉ]", result)


def load_pg_password() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("password="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("PGPASSWORD", "")


def get_conn() -> Any:
    return psycopg2.connect(
        dbname="kimi_rag",
        user="eddie",
        password=load_pg_password(),
        host="localhost",
    )


def verify_endpoint() -> tuple[str, str]:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    embed_url = os.environ.get("OLLAMA_EMBED_URL", f"{host}/api/embed")
    model = os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_MODEL)
    if not host.startswith(("http://", "https://")):
        raise ValueError(f"URL Ollama invalide : {host}")

    request = urllib.request.Request(f"{host}/api/tags")
    with urllib.request.urlopen(request, timeout=8) as response:  # nosemgrep
        payload = json.loads(response.read())
    models = [item.get("name", "") for item in payload.get("models", [])]
    if not any(model.split(":")[0] in name for name in models):
        raise RuntimeError(f"Ollama répond, mais {model} est absent : {models}")
    return embed_url, model


def split_complete_text(text: str) -> list[str]:
    """Découpe structurellement sans abandonner le moindre caractère utile."""
    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        hard_end = min(start + MAX_CHUNK_CHARS, length)
        end = hard_end
        if hard_end < length:
            candidates = [
                text.rfind("\n\n", start + 400, hard_end),
                text.rfind("\n", start + 400, hard_end),
                text.rfind(". ", start + 400, hard_end),
            ]
            boundary = max(candidates)
            if boundary > start:
                end = boundary + (2 if text[boundary : boundary + 2] == ". " else 1)
        chunk = text[start:end]
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - CHUNK_OVERLAP_CHARS, start + 1)
    return chunks


def validate_timeline(path: Path, run_id: str) -> Path:
    path = path.expanduser().resolve()
    allowed = (Path.home() / ".goal" / "runs").resolve()
    if allowed not in path.parents:
        raise ValueError(f"Chemin refusé hors de {allowed}")
    if path.name != "timeline.md" or path.parent.name != run_id:
        raise ValueError("Le manifeste ne correspond pas au run demandé")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def index_document(timeline: Path, run_id: str) -> tuple[int, str, str]:
    """Notifie PostgreSQL immédiatement, même si Ollama est indisponible."""
    content = redact_sensitive(timeline.read_text(encoding="utf-8"))
    if not content.strip():
        raise ValueError("Le manifeste est vide")
    source = str(timeline.relative_to(Path.home()))
    title = f"G.O.A.L. Cascade — run {run_id}"
    now = datetime.now()
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM documents WHERE source = %s ORDER BY id DESC LIMIT 1 FOR UPDATE",
                (source,),
            )
            row = cursor.fetchone()
            if row:
                document_id = row[0]
                cursor.execute(
                    """UPDATE documents
                       SET category = %s, title = %s, content = %s,
                           updated_at = %s, doc_kind = %s, perishability = %s,
                           status = %s, last_verified_at = %s
                       WHERE id = %s""",
                    (
                        "goal-cascade",
                        title,
                        content,
                        now,
                        "etat_date",
                        "lente",
                        "actif",
                        now,
                        document_id,
                    ),
                )
                cursor.execute(
                    "DELETE FROM chunks WHERE doc_id = %s",
                    (document_id,),
                )
            else:
                cursor.execute(
                    """INSERT INTO documents
                       (source, category, title, content, created_at, updated_at,
                        doc_kind, perishability, status, last_verified_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (
                        source,
                        "goal-cascade",
                        title,
                        content,
                        now,
                        now,
                        "etat_date",
                        "lente",
                        "actif",
                        now,
                    ),
                )
                document_id = cursor.fetchone()[0]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return document_id, content, source


def embed_indexed_document(
    document_id: int,
    content: str,
    source: str,
    run_id: str,
) -> dict[str, Any]:
    """Calcule tous les vecteurs sur Ollama puis remplace les chunks atomiquement."""
    embed_url, model_name = verify_endpoint()
    chunks = split_complete_text(content)
    if not chunks:
        raise ValueError("Le manifeste est vide")
    model = OllamaEmbedding(model_name=model_name, url=embed_url, batch_size=1)
    embeddings = list(model.embed(chunks))
    if len(embeddings) != len(chunks):
        raise RuntimeError("Nombre de vecteurs différent du nombre de segments")
    dimensions = {len(vector) for vector in embeddings}
    if dimensions != {1024}:
        raise RuntimeError(f"Dimensions inattendues : {sorted(dimensions)}")

    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM chunks WHERE doc_id = %s", (document_id,))
            chunk_ids = []
            for position, (text, vector) in enumerate(zip(chunks, embeddings)):
                cursor.execute(
                    """INSERT INTO chunks (doc_id, position, text, embedding)
                       VALUES (%s, %s, %s, %s::vector) RETURNING id""",
                    (document_id, position, text, vector.tolist()),
                )
                chunk_ids.append(cursor.fetchone()[0])

            proof_vector = embeddings[0].tolist()
            cursor.execute(
                """SELECT id, 1 - (embedding <=> %s::vector) AS similarity
                   FROM chunks WHERE doc_id = %s AND embedding IS NOT NULL
                   ORDER BY embedding <=> %s::vector LIMIT 1""",
                (proof_vector, document_id, proof_vector),
            )
            proof = cursor.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if not proof or int(proof[0]) not in chunk_ids:
        raise RuntimeError("La relecture vectorielle n'a retrouvé aucun segment du run")

    return {
        "status": "embedded",
        "run_id": run_id,
        "document_id": document_id,
        "chunks": len(chunks),
        "dimensions": 1024,
        "model": model_name,
        "endpoint": embed_url,
        "cosine_similarity": round(float(proof[1]), 8),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "source": source,
        "postgres_indexed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeline", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    document_id = None
    try:
        timeline = validate_timeline(args.timeline, args.run_id)
        document_id, content, source = index_document(timeline, args.run_id)
        if args.index_only:
            result = {
                "status": "indexed_pending_embedding",
                "run_id": args.run_id,
                "document_id": document_id,
                "postgres_indexed": True,
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "source": source,
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        result = embed_indexed_document(
            document_id,
            content,
            source,
            args.run_id,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        payload = {
            "status": ("indexed_pending_embedding" if document_id is not None else "failed"),
            "error_type": type(error).__name__,
            "message": redact_sensitive(str(error)),
            "postgres_indexed": document_id is not None,
        }
        if document_id is not None:
            payload["document_id"] = document_id
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
