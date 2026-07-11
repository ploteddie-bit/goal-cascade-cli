# CI GitHub Actions (pytest + semgrep) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un workflow GitHub Actions qui exécute pytest et semgrep à chaque push/PR sur main.

**Architecture:** Un fichier `.github/workflows/ci.yml` contenant deux jobs indépendants (`test` et `security`). Aucune modification de code Python n'est requise.

**Tech Stack:** GitHub Actions, uv, pytest, semgrep.

## Global Constraints

- Pas de secrets en dur.
- Les tests ne doivent pas dépendre d'Ollama ou PostgreSQL en CI (ils sont déjà isolés).
- Utiliser `uv` cohérent avec l'environnement local.
- Python >= 3.11.
- Ne pas modifier la logique métier.

---

### Task 1: Créer le workflow GitHub Actions

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: workflow GitHub Actions exécutable

- [ ] **Step 1: Create workflow file**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
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

      - name: Run tests
        run: uv run pytest -p no:cacheprovider -q

  security:
    runs-on: ubuntu-latest
    container:
      image: semgrep/semgrep
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Run Semgrep
        run: semgrep scan --config p/secrets --error . && semgrep scan --config p/security-audit --error .
```

- [ ] **Step 2: Validate YAML syntax locally**

Run:
```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```
Expected: no error

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: ajoute workflow pytest + semgrep"
```

---

### Task 2: Ajouter le badge CI dans README.md

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nom du workflow (`CI`) et nom du repo (`ploteddie-bit/goal-cascade-cli`)

- [ ] **Step 1: Insert badge after title**

Add at the top of `README.md`, just after the `# G.O.A.L. Cascade CLI` line:

```markdown
[![CI](https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/ci.yml)
```

- [ ] **Step 2: Verify rendering locally**

Run:
```bash
head -5 README.md
```
Expected: badge line visible

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): ajoute badge CI"
```

---

### Task 3: Pousser et vérifier l'exécution

**Files:**
- None (verification only)

- [ ] **Step 1: Push to GitHub**

Run:
```bash
git push origin main
```
Expected: push successful

- [ ] **Step 2: Verify workflow run**

Open:
```text
https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/ci.yml
```
Expected: workflow run triggered, both jobs green

- [ ] **Step 3: Report result**

If the workflow fails, read the logs and fix.
