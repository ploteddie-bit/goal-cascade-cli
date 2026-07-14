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

### Checklist (~20 min)

| # | Action | Où | Durée |
|---|---|---|---|
| 1 | Commit + push workflow | `git push origin main` | 1 min |
| 2 | Créer environments `pypi` + `testpypi` | GitHub → Settings → Environments | 2 min |
| 3 | Premier run du workflow | GitHub Actions → Run workflow (échec attendu) | 2 min |
| 4 | Ajouter trusted publisher TestPyPI | TestPyPI → Settings → Publishing | 3 min |
| 5 | Ajouter trusted publisher PyPI | PyPI → Settings → Publishing | 3 min |
| 6 | **Dry-run TestPyPI** (obligatoire) | `workflow_dispatch` + cocher `test_pypi` | 5 min |
| 7 | Release production | `git tag vX.Y.Z && git push origin vX.Y.Z` | 1 min |

### 1. Committer et pousser

```bash
git add .github/workflows/release.yml docs/release-procedure.md
git commit -m "ci: release workflow with OIDC trusted publishing"
git push origin main
```

### 2. Créer les environments GitHub (manuel)

Sur <https://github.com/ploteddie-bit/goal-cascade-cli/settings/environments> :
- Créer `pypi` (pas de secrets nécessaires avec OIDC)
- Créer `testpypi` (pas de secrets nécessaires avec OIDC)

### 3. Premier run du workflow (enregistrement GitHub)

> **Problème œuf/poule** : PyPI ne peut vérifier l'existence du workflow que s'il a
> déjà été exécuté au moins une fois. Sans cela, la configuration du trusted publisher
> affiche un warning au lieu d'un statut vert.

1. Aller sur <https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/release.yml>
2. Cliquer **"Run workflow"**
3. Cocher **"Publish to TestPyPI instead of PyPI"**
4. Valider

Le workflow **échouera** à l'étape `publish-testpypi` (trusted publisher pas encore configuré),
mais GitHub aura enregistré que le workflow existe. C'est normal et nécessaire.

| Cas | PyPI peut vérifier ? | Raison |
|---|---|---|
| Workflow sur main mais jamais exécuté | ❌ Non | L'API GitHub ne retourne pas les workflows non exécutés |
| Workflow dans un tag (pas encore poussé) | ❌ Non | Le tag n'existe pas encore |
| Repo privé | ❌ Non | PyPI n'a pas accès à l'API GitHub du repo privé |
| Workflow sur main et déjà exécuté | ✅ Oui | PyPI peut vérifier via l'API |

### 4. Configurer les trusted publishers (manuel)

**TestPyPI** → <https://test.pypi.org/manage/project/goal-cascade/settings/publishing/>

| Champ | Valeur |
|---|---|
| Owner | `ploteddie-bit` |
| Repository | `goal-cascade-cli` |
| Workflow | `release.yml` |
| Environment | `testpypi` |

**PyPI** → <https://pypi.org/manage/project/goal-cascade/settings/publishing/>

Mêmes valeurs avec `Environment: pypi`.

Après le premier run (étape 3), PyPI devrait afficher un **statut vert (active)**.

### 5. ⚠️ Dry-run TestPyPI (OBLIGATOIRE avant tag)

Relancer le workflow pour vérifier que l'OIDC fonctionne maintenant :

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

### 6. Taguer et pousser (seulement si dry-run réussi)

```bash
# Bumper la version dans pyproject.toml au préalable
git tag vX.Y.Z
git push origin vX.Y.Z
```

### 7. Suivre la release production

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
