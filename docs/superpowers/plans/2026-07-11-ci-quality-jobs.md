# CI Quality Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un job `quality` au workflow GitHub Actions existant qui exécute `ruff` (format + lint), `mypy`, `pytest-cov` et `pip-audit`.

**Architecture:** Un seul job `quality` supplémentaire dans `.github/workflows/ci.yml`, exécuté après les jobs `test` et `security`. Les outils sont configurés dans `pyproject.toml` et ajoutés au groupe de dépendances de développement. Aucune dépendance runtime n’est modifiée.

**Tech Stack:** GitHub Actions, uv, ruff, mypy, pytest-cov, pip-audit.

## Global Constraints

- Python `>=3.11`
- `uv` version `0.5.0` dans le workflow CI
- Aucun seuil de couverture bloquant dans cette itération
- `mypy` en mode modéré (`strict = false`)
- Pas de modification de la logique métier
- Les commandes de vérification doivent toutes échouer naturellement en cas de problème (pas de `|| true`)

---

## File Mapping

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Déclare les dépendances de dev et la configuration des outils (ruff, mypy, coverage) |
| `.github/workflows/ci.yml` | Déclare le nouveau job `quality` et ses étapes |

---

### Task 1: Add dev dependencies to `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: existing `[dependency-groups]` section
- Produces: updated dev group with `ruff`, `mypy`, `pytest-cov`, `pip-audit`

- [ ] **Step 1: Update `[dependency-groups.dev]`**

Replace the existing dev group:

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

- [ ] **Step 2: Verify the file syntax**

Run: `uv run python -c "import tomllib, pathlib; tomllib.load(pathlib.Path('pyproject.toml').open('rb'))"`

Expected: command exits with code `0` and no output.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add ruff, mypy, pytest-cov and pip-audit to dev group"
```

---

### Task 2: Configure ruff, mypy and coverage in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: project structure (`src/goal_cascade`)
- Produces: `[tool.ruff]`, `[tool.mypy]`, `[tool.coverage.*]` sections

- [ ] **Step 1: Add `[tool.ruff]` configuration**

Append to `pyproject.toml`:

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

- [ ] **Step 2: Add `[tool.mypy]` configuration**

Append to `pyproject.toml`:

```toml
[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_ignores = true
ignore_missing_imports = true
show_error_codes = true
```

- [ ] **Step 3: Add `[tool.coverage]` configuration**

Append to `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["src/goal_cascade"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false
```

- [ ] **Step 4: Verify the file syntax**

Run: `uv run python -c "import tomllib, pathlib; tomllib.load(pathlib.Path('pyproject.toml').open('rb'))"`

Expected: command exits with code `0` and no output.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml
git commit -m "chore(config): add ruff, mypy and coverage settings"
```

---

### Task 3: Add the `quality` job to `.github/workflows/ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: existing `test` and `security` jobs
- Produces: new `quality` job appended to the workflow

- [ ] **Step 1: Append the `quality` job**

Add the following block at the end of `.github/workflows/ci.yml`, after the `security` job:

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

- [ ] **Step 2: Validate the workflow YAML syntax**

Run: `uv run python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())"`

Expected: command exits with code `0` and no output.

If `pyyaml` is not installed, run instead:

```bash
python3 -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text())"
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add quality job with ruff, mypy, pytest-cov and pip-audit"
```

---

### Task 4: Validate locally and push

**Files:**
- No file changes (verification only)

**Interfaces:**
- Consumes: updated `pyproject.toml`, updated `.github/workflows/ci.yml`
- Produces: local verification evidence and pushed commit(s)

- [ ] **Step 1: Sync dependencies**

Run: `uv sync --dev`

Expected: installs `ruff`, `mypy`, `pytest-cov`, `pip-audit` and their transitive dependencies.

- [ ] **Step 2: Run formatting check**

Run: `uv run ruff format --check .`

Expected: exits `0` if the codebase is already formatted, or lists files to reformat.

If files need reformatting, run `uv run ruff format .` and commit the result with:

```bash
git add -A
git commit -m "style: apply ruff formatting"
```

- [ ] **Step 3: Run linter**

Run: `uv run ruff check .`

Expected: exits `0` or lists lint errors.

If there are auto-fixable errors, run `uv run ruff check . --fix` and commit the result. If there are non-fixable errors, stop and report them to the user before continuing.

- [ ] **Step 4: Run type check**

Run: `uv run mypy src`

Expected: exits `0` or lists type errors.

If there are type errors, stop and report them to the user before continuing.

- [ ] **Step 5: Run tests with coverage**

Run: `uv run pytest -p no:cacheprovider -q --cov=goal_cascade --cov-report=term-missing`

Expected: all tests pass and a coverage summary is printed.

- [ ] **Step 6: Run dependency audit**

Run: `uv run pip-audit --desc`

Expected: exits `0` or lists known vulnerabilities. If vulnerabilities are reported with no available fix, stop and report them to the user.

- [ ] **Step 7: Push and verify CI**

```bash
git push origin main
```

Then watch the latest run:

```bash
gh run watch --repo ploteddie-bit/goal-cascade-cli
```

Expected: all three jobs (`test`, `security`, `quality`) complete successfully.

---

## Self-Review

**Spec coverage:**
- [x] Job unique `quality` — Task 3
- [x] Outils ruff, mypy, pytest-cov, pip-audit — Tasks 1, 3
- [x] Configuration dans `pyproject.toml` — Tasks 1, 2
- [x] Pas de seuil de couverture bloquant — Task 3 step 5 (no `--cov-fail-under`)
- [x] `mypy` modéré — Task 2 step 2 (`strict` not enabled)
- [x] Validation locale — Task 4

**Placeholder scan:**
- [x] No "TBD", "TODO", "implement later"
- [x] No vague requirements
- [x] Exact commands and expected outputs provided

**Type consistency:**
- [x] Paths and package names consistent (`src/goal_cascade`, `goal_cascade` for coverage module name)

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-11-ci-quality-jobs.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using `executing-plans`, batch execution with checkpoints

**Which approach?**
