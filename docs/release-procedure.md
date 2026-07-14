# Procédure de release — goal-cascade

## Prérequis : Trusted Publishers PyPI

### PyPI production

URL : <https://pypi.org/manage/project/goal-cascade/settings/publishing/>

| Champ | Valeur |
|---|---|
| PyPI Project Name | `goal-cascade` |
| Owner | `ploteddie-bit` |
| Repository name | `goal-cascade-cli` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

### TestPyPI

URL : <https://test.pypi.org/manage/project/goal-cascade/settings/publishing/>

| Champ | Valeur |
|---|---|
| PyPI Project Name | `goal-cascade` |
| Owner | `ploteddie-bit` |
| Repository name | `goal-cascade-cli` |
| Workflow name | `release.yml` |
| Environment name | `testpypi` |

## Prérequis : Environments GitHub

Aller sur <https://github.com/ploteddie-bit/goal-cascade-cli/settings/environments> et confirmer que :

- **Environment `pypi`** existe (pas de secrets nécessaires avec OIDC)
- **Environment `testpypi`** existe (pas de secrets nécessaires avec OIDC)

## Séquence de release

### 1. Committer le workflow

```bash
git add .github/workflows/release.yml
git commit -m "ci: replace release workflow with OIDC trusted publishing

- Auto release to PyPI on tag v*.*.*
- Manual TestPyPI via workflow_dispatch
- Includes test gate, twine check, Sigstore signing
- Security: persist-credentials: false, concurrency group"
```

### 2. Pousser

```bash
git push origin main
```

### 3. Taguer et pousser le tag (déclenche la release PyPI)

```bash
git tag v0.4.0
git push origin v0.4.0
```

### 4. Suivre la CI

```bash
gh run watch
```

## Flux du workflow

| Déclencheur | Jobs exécutés |
|---|---|
| `git tag v*.*.*` + push | test → build (twine check) → **publish-pypi** → github-release (Sigstore) |
| `workflow_dispatch` + `test_pypi: true` | test → build (twine check) → **publish-testpypi** |

## Sécurité

- `persist-credentials: false` sur tous les checkouts
- `concurrency: release-${{ github.ref }}` — protection contre double-release
- `uvx twine check dist/*` — validation du package avant publication
- OIDC trusted publishing — pas de token PyPI stocké dans GitHub
- Signature Sigstore sur les artefacts de la GitHub Release
