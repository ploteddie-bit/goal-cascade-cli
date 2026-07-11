# Design — RAG : variable d'environnement, worker versionné et documentation

## Contexte

Le pont RAG (`src/goal_cascade/rag_bridge.py`) et son worker (`~/.kimi/kimi-rag/goal-run-ingest.py`) pointaient vers une adresse Ollama hardcodée (`10.0.0.1:11434`). Cela rend le projet non reproductible sur une autre machine sans modification manuelle du code. Le worker RAG n'est pas versionné dans le repo, donc un clone frais ne peut pas synchroniser les runs.

## Objectifs

1. Remplacer l'IP hardcodée par une variable d'environnement `OLLAMA_HOST` avec fallback localhost.
2. Versionner le worker RAG et son module d'embeddings dans le package `goal_cascade.rag`.
3. Documenter l'installation et la configuration RAG dans `README.md`.

## Architecture

```text
src/goal_cascade/
  rag_bridge.py          # Utilise OLLAMA_HOST et délègue au worker versionné
  rag/
    __init__.py          # Expose worker_path et embed_module_path
    worker.py            # Ancien goal-run-ingest.py (adapté)
    embed.py             # Ancien ollama_embed.py
```

`RagBridge` résout le worker dans l'ordre suivant :
1. `src/goal_cascade/rag/worker.py` (versionné dans le package installé)
2. `~/.kimi/kimi-rag/goal-run-ingest.py` (legacy, pour compatibilité)

Le worker versionné lit `OLLAMA_HOST` et `OLLAMA_EMBED_MODEL` depuis l'environnement avec des fallback raisonnables.

## Détails techniques

### Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | URL base de l'API Ollama |
| `OLLAMA_EMBED_MODEL` | `bge-m3:latest` | Modèle d'embeddings utilisé |

### `rag_bridge.py`

- `IA_GENERAL_HOST` devient `os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")`.
- `IA_GENERAL_EMBED_URL` reste dérivé de `IA_GENERAL_HOST`.
- `RagBridge.__init__` résout `self.worker_path` en cherchant d'abord le worker versionné.
- Les variables `embedding_host` dans `rag-status.json` passent de la chaîne littérale `"ia-general"` à la valeur nette de `OLLAMA_HOST` (sans `http://`) pour rester informatif sans exposer de protocole inutile.

### `rag/worker.py`

- Copie fonctionnelle de `~/.kimi/kimi-rag/goal-run-ingest.py`.
- `EXPECTED_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")`.
- `MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3:latest")`.
- Chemins relatifs ajustés pour être exécuté depuis n'importe quel répertoire (utilisation de `Path(__file__).resolve().parent`).
- Redaction des secrets conservée.

### `rag/embed.py`

- Copie fonctionnelle de `~/.kimi/kimi-rag/ollama_embed.py`.
- Utilise `OLLAMA_HOST` et `OLLAMA_EMBED_MODEL` si elles existent, sinon fallback aux valeurs par défaut.

### Tests

- `tests/test_audit_journal.py` : mettre à jour les tests pour refléter le fallback localhost quand `OLLAMA_HOST` n'est pas définie.
- Ajouter un test qui vérifie que `RagBridge` trouve le worker versionné.
- Ajouter un test qui vérifie que `OLLAMA_HOST` est propagé dans l'environnement du worker.

### Documentation

Ajouter dans `README.md` une section **RAG et traces d'exécution** couvrant :
- Où sont stockés les runs (`~/.goal/runs/<run_id>/`).
- Commande `goal rag-sync <run_id>`.
- Prérequis Ollama local ou distant.
- Variables `OLLAMA_HOST` et `OLLAMA_EMBED_MODEL`.
- Localisation du worker versionné.

## Non-objectifs

- Ne pas rendre PostgreSQL optionnel : le RAG reste conçu pour une base PostgreSQL locale.
- Ne pas refactoriser la logique d'indexation : on déplace et adapte, on ne réécrit pas.
- Ne pas changer le format du `rag-status.json` (hors champ `embedding_host`).

## Critères de succès

- `uv run pytest -p no:cacheprovider -q` passe (60+ tests).
- `uv run goal rag-sync <run_id>` fonctionne avec `OLLAMA_HOST=http://10.0.0.1:11434`.
- `uv run goal rag-sync <run_id>` fonctionne aussi sans `OLLAMA_HOST` défini si Ollama tourne en localhost.
- Le repo contient `src/goal_cascade/rag/worker.py` et `src/goal_cascade/rag/embed.py`.
- `README.md` explique la configuration RAG.
