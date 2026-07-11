# Design — CI GitHub Actions (pytest + semgrep)

## Contexte

Le projet `goal-cascade-cli` n'a pas encore de CI. Les vérifications manuelles (pytest + semgrep) sont fiables mais doivent être automatisées pour garantir la qualité à chaque contribution.

## Objectifs

1. Exécuter automatiquement `pytest` à chaque push et chaque PR sur `main`.
2. Exécuter automatiquement `semgrep` (secrets + security-audit) sur le même déclencheur.
3. Utiliser `uv` pour la gestion des dépendances Python, cohérent avec l'environnement de développement local.
4. Ne pas dépendre de services externes (Ollama, PostgreSQL) en CI — les tests doivent rester isolés.

## Architecture

Un seul workflow `.github/workflows/ci.yml` avec deux jobs indépendants :

- **`test`** : installe uv + Python 3.11, synchronise le projet, lance `uv run pytest -p no:cacheprovider -q`.
- **`security`** : exécute Semgrep avec les configs `p/secrets` et `p/security-audit` via l'action officielle `semgrep/semgrep`.

Les deux jobs tournent sur `ubuntu-latest` et sont indépendants (le plus lent ne bloque pas l'autre).

## Détails techniques

### Déclencheurs

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

### Job `test`

- OS : `ubuntu-latest`
- Python : `3.11` (version minimale du projet)
- Étapes :
  1. `actions/checkout@v4`
  2. `astral-sh/setup-uv@v5`
  3. `uv python install 3.11`
  4. `uv sync --dev`
  5. `uv run pytest -p no:cacheprovider -q`

### Job `security`

- Utilise l'image `semgrep/semgrep` officielle
- Étapes :
  1. `actions/checkout@v4`
  2. `semgrep/semgrep-action@v1` avec `config: >- p/secrets p/security-audit`

## Non-objectifs

- Pas de déploiement automatique (hors scope).
- Pas de cache Docker ou de build de package (peut être ajouté plus tard).
- Pas de matrice multi-version Python dans un premier temps (3.11 suffit).

## Critères de succès

- Le workflow s'exécute avec succès sur `main` après le merge.
- `pytest` passe.
- `semgrep` ne remonte aucun finding bloquant.
- Le badge CI est visible dans `README.md` (optionnel mais recommandé).
