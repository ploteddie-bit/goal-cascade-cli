# RAG : variable d'environnement, worker versionné et documentation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre le pont RAG reproductible sans IP hardcodée en versionnant le worker et en externalisant la configuration Ollama via des variables d'environnement.

**Architecture:** On crée un package `goal_cascade.rag` contenant le worker versionné et son module d'embeddings. `rag_bridge.py` utilise `OLLAMA_HOST`/`OLLAMA_EMBED_MODEL` avec fallback localhost, et délègue au worker versionné s'il est présent, sinon au worker legacy dans `~/.kimi/kimi-rag/`. Le README documente la configuration.

**Tech Stack:** Python 3.12+, uv, pytest, psycopg2, numpy, urllib.

## Global Constraints

- Pas de secrets en dur.
- `mypy --strict` en CI : type hints obligatoires.
- Tests sous `tests/` avec pytest.
- Le fallback par défaut est `http://127.0.0.1:11434` et `bge-m3:latest`.
- Le worker versionné ne doit plus refuser un endpoint différent de `ia-general`.
- Le format public du `rag-status.json` reste inchangé (hors champ `embedding_host`).

---

### Task 1: Créer `src/goal_cascade/rag/__init__.py`

**Files:**
- Create: `src/goal_cascade/rag/__init__.py`

**Interfaces:**
- Produces: `default_ollama_host() -> str`, `default_ollama_embed_url() -> str`, `default_ollama_embed_model() -> str`, `resolve_worker_path() -> Path`, `resolve_embed_module_path() -> Path`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rag_package.py
from pathlib import Path

from goal_cascade.rag import (
    default_ollama_embed_model,
    default_ollama_embed_url,
    default_ollama_host,
    resolve_embed_module_path,
    resolve_worker_path,
)


def test_defaults_use_localhost() -> None:
    assert default_ollama_host() == "http://127.0.0.1:11434"
    assert default_ollama_embed_url() == "http://127.0.0.1:11434/api/embed"
    assert default_ollama_embed_model() == "bge-m3:latest"


def test_resolve_worker_path_points_to_versioned_worker() -> None:
    path = resolve_worker_path()
    assert path.name == "worker.py"
    assert "src/goal_cascade/rag" in str(path)


def test_resolve_embed_module_path_points_to_versioned_embed() -> None:
    path = resolve_embed_module_path()
    assert path.name == "embed.py"
    assert "src/goal_cascade/rag" in str(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rag_package.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'goal_cascade.rag'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/goal_cascade/rag/__init__.py
"""Package RAG versionné pour G.O.A.L. Cascade."""

from __future__ import annotations

import os
from pathlib import Path


def default_ollama_host() -> str:
    """URL de base Ollama par défaut, configurable via OLLAMA_HOST."""
    return os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def default_ollama_embed_url() -> str:
    """URL de l'endpoint embeddings Ollama par défaut."""
    return os.environ.get("OLLAMA_EMBED_URL", f"{default_ollama_host()}/api/embed")


def default_ollama_embed_model() -> str:
    """Modèle d'embeddings par défaut, configurable via OLLAMA_EMBED_MODEL."""
    return os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3:latest")


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def resolve_worker_path() -> Path:
    """Chemin du worker RAG versionné dans le package."""
    return _package_dir() / "worker.py"


def resolve_embed_module_path() -> Path:
    """Chemin du module d'embeddings versionné dans le package."""
    return _package_dir() / "embed.py"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rag_package.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/goal_cascade/rag/__init__.py tests/test_rag_package.py
git commit -m "feat(rag): ajoute le package rag avec helpers de configuration Ollama"
```

---

### Task 2: Créer `src/goal_cascade/rag/embed.py`

**Files:**
- Create: `src/goal_cascade/rag/embed.py`

**Interfaces:**
- Consumes: variables d'environnement `OLLAMA_EMBED_URL`, `OLLAMA_EMBED_MODEL`
- Produces: `class OllamaEmbedding` avec méthode `.embed(texts, normalize=True)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rag_embed.py
from unittest.mock import patch

from goal_cascade.rag.embed import OllamaEmbedding


def test_ollama_embedding_uses_env_defaults(monkeypatch) -> None:
    monkeypatch.delenv("OLLAMA_EMBED_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    emb = OllamaEmbedding()
    assert emb.url == "http://127.0.0.1:11434/api/embed"
    assert emb.model_name == "bge-m3:latest"


def test_ollama_embedding_uses_env_variables(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_EMBED_URL", "http://10.0.0.1:11434/api/embed")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "custom-model")
    emb = OllamaEmbedding()
    assert emb.url == "http://10.0.0.1:11434/api/embed"
    assert emb.model_name == "custom-model"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rag_embed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'goal_cascade.rag.embed'`

- [ ] **Step 3: Write minimal implementation**

Copier le contenu de `~/.kimi/kimi-rag/ollama_embed.py` dans `src/goal_cascade/rag/embed.py`, en remplaçant les constantes globales par des fallback localhost et en ajoutant une docstring.

```python
# src/goal_cascade/rag/embed.py
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

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/embed"
DEFAULT_EMBED_MODEL = "bge-m3:latest"
EMBED_DIM = 1024
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
        self.model_name = model_name or os.environ.get(
            "OLLAMA_EMBED_MODEL", DEFAULT_EMBED_MODEL
        )
        self.url = url or os.environ.get("OLLAMA_EMBED_URL", DEFAULT_OLLAMA_URL)
        self.batch_size = batch_size

    def _post(self, inputs: list[str]) -> list[list[float]]:
        payload = json.dumps(
            {"model": self.model_name, "input": inputs, "truncate": True}
        ).encode()
        req = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
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
                    return self._embed_batch(inputs[:mid]) + self._embed_batch(
                        inputs[mid:]
                    )
                last_err = e
                time.sleep(2 * (attempt + 1))
            except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, RuntimeError) as e:
                reason = getattr(e, "reason", e)
                is_timeout = isinstance(e, (TimeoutError, socket.timeout)) or isinstance(
                    reason, (TimeoutError, socket.timeout)
                )
                if is_timeout and len(inputs) > 1:
                    mid = len(inputs) // 2
                    return self._embed_batch(inputs[:mid]) + self._embed_batch(
                        inputs[mid:]
                    )
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(
            f"[ollama_embed] échec après {RETRIES} essais sur {self.url}: {last_err}"
        )

    def embed(
        self, texts: Iterable[str], normalize: bool = True
    ) -> Iterable[np.ndarray]:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rag_embed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/goal_cascade/rag/embed.py tests/test_rag_embed.py
git commit -m "feat(rag): versionne le module d'embeddings Ollama"
```

---

### Task 3: Créer `src/goal_cascade/rag/worker.py`

**Files:**
- Create: `src/goal_cascade/rag/worker.py`

**Interfaces:**
- Consumes: `OLLAMA_HOST`, `OLLAMA_EMBED_URL`, `OLLAMA_EMBED_MODEL` ; module `goal_cascade.rag.embed`
- Produces: script exécutable qui accepte `--timeline`, `--run-id`, `--index-only`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rag_worker.py
from pathlib import Path

from goal_cascade.rag.worker import verify_endpoint


def test_verify_endpoint_uses_env_host(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.1:11434")
    monkeypatch.delenv("OLLAMA_EMBED_URL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    # On mock la vérification HTTP pour ne pas dépendre d'Ollama en test
    import urllib.request

    original_urlopen = urllib.request.urlopen

    def fake_urlopen(req, **kwargs):
        class FakeResponse:
            def read(self):
                return b'{"models":[{"name":"bge-m3:latest"}]}'
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    embed_url, model = verify_endpoint()
    assert embed_url == "http://10.0.0.1:11434/api/embed"
    assert model == "bge-m3:latest"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_rag_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'goal_cascade.rag.worker'`

- [ ] **Step 3: Write minimal implementation**

Copier le contenu de `~/.kimi/kimi-rag/goal-run-ingest.py` dans `src/goal_cascade/rag/worker.py`, avec les modifications suivantes :

1. Remplacer l'import `from ollama_embed import OllamaEmbedding` par `from goal_cascade.rag.embed import OllamaEmbedding`.
2. Remplacer `SCRIPT_DIR = Path(__file__).resolve().parent` par `PACKAGE_DIR = Path(__file__).resolve().parent` et `sys.path.insert(0, str(PACKAGE_DIR))`.
3. Remplacer les constantes globales par :

```python
DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_EMBED_URL = f"{DEFAULT_HOST}/api/embed"
DEFAULT_MODEL = "bge-m3:latest"
```

4. Modifier `verify_endpoint()` pour supprimer le refus systématique d'un endpoint non-ia-general :

```python
def verify_endpoint() -> tuple[str, str]:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")
    embed_url = os.environ.get("OLLAMA_EMBED_URL", f"{host}/api/embed")
    model = os.environ.get("OLLAMA_EMBED_MODEL", DEFAULT_MODEL)

    request = urllib.request.Request(f"{host}/api/tags")
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read())
    models = [item.get("name", "") for item in payload.get("models", [])]
    if not any(model.split(":")[0] in name for name in models):
        raise RuntimeError(f"Ollama répond, mais {model} est absent : {models}")
    return embed_url, model
```

5. Conserver `redact_sensitive`, `load_pg_password`, `get_conn`, `split_complete_text`, `validate_timeline`, `index_document`, `embed_indexed_document`, `main` tels quels (à l'adaptation des constantes près).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_rag_worker.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/goal_cascade/rag/worker.py tests/test_rag_worker.py
git commit -m "feat(rag): versionne le worker d'indexation RAG"
```

---

### Task 4: Modifier `src/goal_cascade/rag_bridge.py`

**Files:**
- Modify: `src/goal_cascade/rag_bridge.py`

**Interfaces:**
- Consumes: `goal_cascade.rag.default_ollama_host`, `goal_cascade.rag.resolve_worker_path`
- Produces: `RagBridge` utilise le worker versionné par défaut et `OLLAMA_HOST`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/test_audit_journal.py` :

```python
def test_rag_bridge_uses_versioned_worker_first(tmp_path) -> None:
    from goal_cascade.rag import resolve_worker_path
    bridge = RagBridge()
    # Si le worker versionné existe, il doit être utilisé
    if resolve_worker_path().exists():
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
        return CompletedProcess(command, 1, stdout="", stderr='{"status":"failed","message":"nope"}')

    bridge = RagBridge(worker_path=worker, interpreter=interpreter, runner=runner)
    with pytest.raises(RagSyncError):
        bridge.sync_run("rag-env", journal=journal)
    assert captured["env"]["OLLAMA_HOST"] == "http://10.0.0.1:11434"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_journal.py::test_rag_bridge_uses_versioned_worker_first tests/test_audit_journal.py::test_rag_bridge_propagates_ollama_host -v`
Expected: FAIL — `ImportError` ou `AttributeError`

- [ ] **Step 3: Write minimal implementation**

Modifier `src/goal_cascade/rag_bridge.py` :

1. Remplacer les imports en haut du fichier :

```python
from goal_cascade.rag import (
    default_ollama_embed_model,
    default_ollama_embed_url,
    default_ollama_host,
    resolve_worker_path,
)
```

2. Remplacer les constantes globales :

```python
IA_GENERAL_HOST = default_ollama_host()
IA_GENERAL_EMBED_URL = default_ollama_embed_url()
```

3. Modifier `RagBridge.__init__` pour résoudre le worker versionné en priorité :

```python
def __init__(
    self,
    worker_path: Path | None = None,
    interpreter: Path | None = None,
    runner: Callable = subprocess.run,
    timeout_s: int = 900,
):
    versioned_worker = resolve_worker_path()
    self.worker_path = worker_path or (
        versioned_worker if versioned_worker.exists() else Path.home() / ".kimi" / "kimi-rag" / "goal-run-ingest.py"
    )
    self.interpreter = interpreter or (Path.home() / ".kimi" / "kimi-rag" / "venv" / "bin" / "python")
    self.runner = runner
    self.timeout_s = timeout_s
```

4. Dans `sync_run`, utiliser `default_ollama_embed_model()` et propager `OLLAMA_HOST`/`OLLAMA_EMBED_URL`/`OLLAMA_EMBED_MODEL` :

```python
env["OLLAMA_HOST"] = IA_GENERAL_HOST
env["OLLAMA_EMBED_URL"] = IA_GENERAL_EMBED_URL
env["OLLAMA_EMBED_MODEL"] = default_ollama_embed_model()
```

5. Remplacer toutes les occurrences de la chaîne littérale `"ia-general"` dans `journal.record_event` / `journal.update_rag_status` par une valeur dérivée de `IA_GENERAL_HOST` (par exemple `IA_GENERAL_HOST.replace("http://", "").replace("https://", "").split(":")[0]`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audit_journal.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/goal_cascade/rag_bridge.py tests/test_audit_journal.py
git commit -m "feat(rag): utilise OLLAMA_HOST et worker versionné dans RagBridge"
```

---

### Task 5: Mettre à jour la suite de tests complète

**Files:**
- Modify: `tests/test_audit_journal.py`

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -p no:cacheprovider -q`
Expected: PASS (60+ tests)

- [ ] **Step 2: Fix any regressions**

Si des tests échouent à cause du changement de `embedding_host` ou de valeurs par défaut, ajuster les assertions pour refléter les nouvelles valeurs localhost.

- [ ] **Step 3: Commit**

```bash
git add tests/test_audit_journal.py
git commit -m "test(rag): ajuste les tests pour OLLAMA_HOST et worker versionné"
```

---

### Task 6: Documenter dans `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add RAG section**

Insérer avant la section `## Tests` :

```markdown
## RAG et traces d'exécution

Chaque run produit une trace dans `~/.goal/runs/<run_id>/` :

- `timeline.md` : manifeste complet de la cascade
- `events.jsonl` : événements structurés
- `rag-status.json` : preuve d'indexation PostgreSQL + embeddings

Pour synchroniser un run dans le RAG PostgreSQL local :

```bash
# Ollama local avec bge-m3:latest
goal rag-sync <run_id>

# Ollama distant (par exemple serveur-io-ia)
export OLLAMA_HOST=http://10.0.0.1:11434
goal rag-sync <run_id>
```

Variables d'environnement :

| Variable | Défaut | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | URL de l'API Ollama |
| `OLLAMA_EMBED_URL` | `$OLLAMA_HOST/api/embed` | Endpoint embeddings |
| `OLLAMA_EMBED_MODEL` | `bge-m3:latest` | Modèle d'embeddings |

Le worker RAG versionné se trouve dans `src/goal_cascade/rag/worker.py`. En production, il est utilisé en priorité ; sinon le pont retombe sur `~/.kimi/kimi-rag/goal-run-ingest.py`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): documente la configuration RAG et Ollama"
```

---

### Task 7: Vérification end-to-end et push

**Files:**
- None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest -p no:cacheprovider -q`
Expected: PASS

- [ ] **Step 2: Run semgrep security scan**

Run:
```bash
semgrep scan --config p/secrets --error .
semgrep scan --config p/security-audit --error .
```
Expected: 0 findings

- [ ] **Step 3: Test RAG sync with remote Ollama**

Run:
```bash
export OLLAMA_HOST=http://10.0.0.1:11434
uv run goal rag-sync 83a472d6
```
Expected: `status: embedded`, `chunks: 43`, `cosine_similarity: 1.0`

- [ ] **Step 4: Push to GitHub**

```bash
git push origin main
```

Expected: push successful
