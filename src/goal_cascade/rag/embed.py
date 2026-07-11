"""Backend d'embedding via Ollama (drop-in pour fastembed.TextEmbedding)."""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from typing import Iterable

import numpy as np

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_URL = f"{DEFAULT_OLLAMA_HOST}/api/embed"
DEFAULT_EMBED_MODEL = "bge-m3:latest"
DEFAULT_BATCH = 1
TIMEOUT = 180
RETRIES = 3


class OllamaEmbedding:
    """Drop-in minimal pour fastembed.TextEmbedding (méthode .embed)."""

    def __init__(
        self,
        model_name: str | None = None,
        url: str | None = None,
        batch_size: int = DEFAULT_BATCH,
    ):
        self.model_name = model_name or os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
        if url:
            self.url = url
        else:
            host = os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")
            self.url = os.environ.get("OLLAMA_EMBED_URL", f"{host}/api/embed").rstrip("/")
        self.batch_size = batch_size

    def _post(self, inputs: list[str]) -> list[list[float]]:
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"URL Ollama invalide : {self.url}")
        payload = json.dumps({"model": self.model_name, "input": inputs, "truncate": True}).encode()
        req = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosemgrep
            data = json.loads(resp.read())
        embs = data.get("embeddings")
        if not embs:
            raise RuntimeError(f"réponse sans embeddings: {str(data)[:200]}")
        return embs

    def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        last_err: Exception | None = None
        for attempt in range(RETRIES):
            try:
                return self._post(inputs)
            except urllib.error.HTTPError as e:
                if e.code == 400 and len(inputs) > 1:
                    mid = len(inputs) // 2
                    return self._embed_batch(inputs[:mid]) + self._embed_batch(inputs[mid:])
                last_err = e
                time.sleep(2 * (attempt + 1))
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                OSError,
                RuntimeError,
            ) as e:
                reason = getattr(e, "reason", e)
                is_timeout = isinstance(e, (TimeoutError, socket.timeout)) or isinstance(
                    reason, (TimeoutError, socket.timeout)
                )
                if is_timeout and len(inputs) > 1:
                    mid = len(inputs) // 2
                    return self._embed_batch(inputs[:mid]) + self._embed_batch(inputs[mid:])
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(
            f"[ollama_embed] échec après {RETRIES} essais sur {self.url}: {last_err}"
        )

    def embed(self, texts: Iterable[str], normalize: bool = True) -> Iterable[np.ndarray]:
        MAX_CHARS = 1500
        texts = list(texts)
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            safe: list[str] = []
            for t in batch:
                t = t.strip() if t else " "
                if len(t) > MAX_CHARS:
                    t = t[:MAX_CHARS]
                safe.append(t)
            for vec in self._embed_batch(safe):
                arr = np.asarray(vec, dtype=np.float32)
                if normalize:
                    norm = np.linalg.norm(arr)
                    if norm > 0:
                        arr = arr / norm
                yield arr


if __name__ == "__main__":
    m = OllamaEmbedding()
    out = list(m.embed(["test de l'embedding bge-m3", "deuxième phrase"]))
    print(f"OK — {len(out)} vecteurs, dimension = {len(out[0])}")
