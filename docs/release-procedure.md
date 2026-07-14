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

### Checklist (~16 min)

| # | Action | Où | Durée |
|---|---|---|---|
| 1 | Créer environment `testpypi` | GitHub → Settings → Environments | 2 min |
| 2 | Créer environment `pypi` | GitHub → Settings → Environments | 2 min |
| 3 | Ajouter trusted publisher | TestPyPI → Settings → Publishing | 3 min |
| 4 | Ajouter trusted publisher | PyPI → Settings → Publishing | 3 min |
| 5 | **Dry-run TestPyPI** (obligatoire) | `workflow_dispatch` + cocher `test_pypi` | 5 min |
| 6 | Release production | `git tag vX.Y.Z && git push origin vX.Y.Z` | 1 min |

### 1. Committer et pousser

```bash
git add .github/workflows/release.yml docs/release-procedure.md
git commit -m "ci: release workflow with OIDC trusted publishing"
git push origin main
```

### 2. Configurer les environments et trusted publishers (manuel)

- Créer `pypi` et `testpypi` sur [GitHub Environments](https://github.com/ploteddie-bit/goal-cascade-cli/settings/environments) (pas de secrets nécessaires avec OIDC)
- Configurer les trusted publishers sur [PyPI](https://pypi.org/manage/project/goal-cascade/settings/publishing/) et [TestPyPI](https://test.pypi.org/manage/project/goal-cascade/settings/publishing/)

### 3. ⚠️ Dry-run TestPyPI (OBLIGATOIRE avant tag)

1. Aller sur <https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/release.yml>
2. Cliquer **"Run workflow"**
3. Cocher **"Publish to TestPyPI instead of PyPI"**
4. Valider et suivre avec `gh run watch`

> **Pourquoi avant le tag ?** Le `workflow_dispatch` avec `test_pypi: true` déclenche uniquement
> le job `publish-testpypi`, sans toucher à PyPI production. C'est le seul moyen de vérifier
> que l'OIDC fonctionne avant de taguer.
>
> - Si le dry-run **passe** → taguer en confiance.
> - Si le dry-run **échoue** → corriger sans polluer l'historique des versions.

### 4. Taguer et pousser (seulement si dry-run réussi)

```bash
# Bumper la version dans pyproject.toml au préalable
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 5. Suivre la release production

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
