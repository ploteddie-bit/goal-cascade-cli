# Design — Jobs qualité CI (ruff, mypy, couverture, pip-audit)

**Date :** 2026-07-11  
**Auteur :** Kimi Code CLI  
**Statut :** Proposition validée par l’utilisateur

---

## 1. Contexte

Le workflow CI actuel (`docs/superpowers/specs/2026-07-11-github-actions-ci-design.md`) comporte deux jobs :

- `test` : exécute `pytest`
- `security` : exécute `semgrep` pour les secrets et l’audit de sécurité

Ce design ajoute un **job unique `quality`** qui regroupe les vérifications de qualité du code Python : formatage, linting, typage statique, couverture de tests et audit des dépendances.

---

## 2. Objectifs

- Détecter automatiquement les problèmes de style et de formatage (`ruff`).
- Vérifier la cohérence des annotations de type (`mypy`).
- Mesurer et afficher la couverture de tests (`pytest-cov`) **sans seuil bloquant** dans un premier temps.
- Détecter les vulnérabilités connues dans les dépendances tierces (`pip-audit`).
- Garder le workflow CI simple et rapide à maintenir.

---

## 3. Approche retenue

**Approche B — un seul job `quality`.**

Les quatre outils s’exécutent séquentiellement dans un même job après un unique setup (checkout, uv, Python, dépendances). Cela minimise la duplication de configuration et la consommation de minutes GitHub Actions.

L’ordre d’exécution est choisi pour le retour rapide :

1. `ruff format --check` — rapide, échec visible immédiatement
2. `ruff check` — rapide, détecte les problèmes de style et imports
3. `mypy src` — typage statique
4. `pytest --cov=goal_cascade --cov-report=term-missing` — tests + couverture
5. `pip-audit --desc` — audit dépendances

---

## 4. Outils et justifications

| Outil | Rôle | Pourquoi |
|-------|------|----------|
| `ruff` | Lint + format | Remplace `flake8`, `black`, `isort` ; très rapide ; standard Astral |
| `mypy` | Vérification des types | Outil de référence pour Python ; détecte les incohérences d’annotations |
| `pytest-cov` | Couverture de tests | S’intègre nativement à pytest ; affiche le taux global et les lignes manquantes |
| `pip-audit` | Audit dépendances | Développé par PyPA ; compare les packages installés à la base `PyPI Advisory DB` |

---

## 5. Configuration

### 5.1 `pyproject.toml` — dépendances de développement

Ajouter dans `[dependency-groups.dev]` :

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
    "mypy>=1.10",
    "pytest-cov>=5.0",
    "pip-audit>=2.7",
]
```

### 5.2 `pyproject.toml` — configuration `ruff`

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "F",   # Pyflakes
    "I",   # isort
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "SIM", # flake8-simplify
]
ignore = ["E501"]  # longueurs de ligne gérées par line-length
```

### 5.3 `pyproject.toml` — configuration `mypy`

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_ignores = true
ignore_missing_imports = true
show_error_codes = true
```

> **Note :** `strict = false` pour la première itération afin d’éviter un trop grand nombre d’erreurs sur le code existant. Le passage à `strict = true` pourra faire l’objet d’un chantier ultérieur.

### 5.4 `pyproject.toml` — configuration `coverage`

```toml
[tool.coverage.run]
source = ["src/goal_cascade"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false
```

> **Note :** Aucun `fail_under` n’est défini dans un premier temps. Le taux de couverture est affiché dans les logs CI pour établir une ligne de base avant d’imposer un seuil.

---

## 6. Mise à jour du workflow `.github/workflows/ci.yml`

Ajouter le job suivant à la suite des jobs existants `test` et `security` :

```yaml
  quality:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          version: "0.5.0"

      - name: Install Python
        run: uv python install 3.11

      - name: Install dependencies
        run: uv sync --dev

      - name: Check formatting
        run: uv run ruff format --check .

      - name: Run linter
        run: uv run ruff check .

      - name: Type check
        run: uv run mypy src

      - name: Run tests with coverage
        run: uv run pytest -p no:cacheprovider -q --cov=goal_cascade --cov-report=term-missing

      - name: Audit dependencies
        run: uv run pip-audit --desc
```

---

## 7. Gestion des erreurs

Chaque étape du job `quality` échoue naturellement en cas de problème. Aucune commande n’est lancée avec `|| true` ou `continue-on-error` : si une vérification échoue, le workflow est marqué en échec.

En cas d’échec de `pip-audit` lié à une dépendance sans correctif disponible, l’équipe pourra décider d’ajouter une exception temporaire dans la configuration de `pip-audit`. Ce cas sera traité au moment de l’implémentation si nécessaire.

---

## 8. Stratégie de couverture

La première itération se contente de **mesurer et afficher** la couverture. Un seuil bloquant (`--cov-fail-under`) ne sera ajouté que lorsque la ligne de base sera connue et acceptée.

Cette approche évite de bloquer des PRs légitimes à cause d’un seuil arbitraire fixé trop tôt.

---

## 9. Validation

Avant de pousser sur `main`, les commandes suivantes doivent passer en local :

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest -p no:cacheprovider -q --cov=goal_cascade --cov-report=term-missing
uv run pip-audit --desc
```

Après poussée, vérifier que le run GitHub Actions affiche les trois jobs (`test`, `security`, `quality`) verts.

---

## 10. Non-objectifs

- Ne pas remplacer le job `security` existant (Semgrep reste responsable des secrets et de l’audit de code).
- Ne pas ajouter de seuil de couverture bloquant dans cette itération.
- Ne pas activer `mypy --strict` dans cette itération.
- Ne pas modifier la logique métier du projet.

---

## 11. Prochaines étapes possibles

- Ajuster `mypy` vers `strict = true` une fois le code nettoyé.
- Fixer un seuil de couverture après observation de la ligne de base.
- Ajouter un upload du rapport de couverture vers un service externe (Codecov, etc.) si besoin.
