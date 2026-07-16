# G.O.A.L. Cascade CLI

[![CI](https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/ploteddie-bit/goal-cascade-cli/actions/workflows/ci.yml)

Framework **Goal-Oriented Agentic Loop** : cascade multi-agents pour produire des livrables de haute qualité avec transparence radicale des coûts, sécurité E2E et résilience provider.

## État — version `0.4.0`

La source de vérité du produit est la [spécification d'implémentation V2](docs/specs/goal-cascade-implementation-v2.md). Les jalons S1 à S6 sont implémentés et testés (282 tests passent) :

- **S1 Fondations** : cascade unique 4 rôles (producteur, critique, adversaire, arbitre), synthèse orientée objectif, artefacts immuables séparés, verdict JSON validé, borne stricte de 5 itérations.
- **S2 Multi-provider** : `anthropic`, `openai`, `google` via Mirascope, plus `mock`, `kimi-cli`, `kimi-code`. Rate limit configurable, chaîne de fallback respectant la diversité de familles (Pilier 1).
- **S3 Qualité synthèse** : détection de dérive cosinus (`bge-m3`), mode `--no-synth`, mesure de couverture synthèse vs sortie brute.
- **S4 LangGraph + budget** : graphe d'états à 6 nœuds, checkpoints SQLite, kill switch budgétaire (`[budget]` TOML), `goal resume`.
- **S5 Cache + versioning** : cache sémantique SQLite + embeddings, `goal versions` / `goal diff` / `goal inspect`.
- **S6 Multi-cascade + CI/CD** : `goal plan` (LLM ou squelettique), `goal cascade-run` (exécuteur topologique), `--enrich-frozen-specs` (2e appel LLM via `frozen_spec_gen.j2`), hook CI/CD déterministe câblé dans la cascade unique.

**Sécurité** (audits A-F passés, voir [Security](#security)) : pas de secrets dans les logs, traces en `0o700`, `.gitignore` complet, hook déterministe avant LLM, STOP par défaut, diversité providers validée au démarrage.

## Quick start

```bash
# 1. Installation (mode dev)
uv sync --dev

# 2. Smoke test (aucune clé API requise)
uv run goal run --objective "Auditer un argument" --provider mock --variant A

# 3. Avec un vrai provider (installer l'extra llm)
uv pip install -e '.[llm]'
export ANTHROPIC_API_KEY=sk-ant-...
uv run goal run --objective "..." --provider anthropic

# 4. Multi-cascade
uv run goal plan spec.md --enrich-frozen-specs
uv run goal cascade-run plan.json
```

L'installation comme commande utilisateur est documentée plus bas.

## Installation

### Développement

```bash
uv sync --dev
uv run goal --help
```

### Commande utilisateur (WSL)

```bash
uv tool install --force --editable /mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli
goal --help
```

### Extra `llm` (providers réels)

```bash
pip install 'goal-cascade[llm]'
# Ajoute : mirascope>=1.0, anthropic>=0.40, structlog>=24.0
```

Sans cet extra, seuls `mock`, `kimi-cli`, `kimi-code` sont disponibles.

## Commandes principales

| Commande | Rôle |
|---|---|
| `goal run --objective "..."` | Lance une cascade unique |
| `goal plan spec.md` | Génère un plan multi-cascade depuis un spec |
| `goal cascade-run plan.json` | Exécute toutes les cascades d'un plan |
| `goal resume <run_id>` | Reprend un run interrompu (checkpoint SQLite) |
| `goal status / list / inspect` | Consultation des runs |
| `goal versions / diff` | Versioning et diff entre runs |
| `goal rag-status / rag-sync` | Synchronisation RAG PostgreSQL |

Options globales utiles :

| Option | Effet |
|---|---|
| `--provider` | `mock`, `kimi-cli`, `kimi-code`, `anthropic`, `openai`, `google` |
| `--config PATH` | Charger `~/.goal/config.toml` (résout providers par rôle + budget + rate limit) |
| `--variant A\|B` | A = rédactionnel, B = technique |
| `--no-synth` | Désactiver la synthèse orientée objectif (debug) |
| `--enrich-frozen-specs` | 2e appel LLM pour enrichir les frozen specs (opt-in) |

### Note : `--provider` (singulier) vs `--providers` (pluriel selon spec)

La spec d'implémentation V2 mentionne `--providers anthropic,openai,google` (pluriel, liste séparée par virgules). **Le flag implémenté est `--provider` au singulier** — la cascade utilise un seul provider pour tous les rôles.

Pour mapper un provider différent par rôle (par exemple `anthropic` pour le producteur, `openai` pour le critique), utilisez le fichier de configuration TOML avec `role_mapping` :

```toml
[providers]
enabled = ["anthropic", "openai", "google"]
role_mapping = { producer = "anthropic", critic = "openai", adversary = "google", arbiter = "google" }
```

Voir la section [Configuration TOML](#configuration-toml) pour le schéma complet.

> **Note** : les providers réels (`anthropic`, `openai`, `google`) nécessitent l'installation de l'extra `llm` :
> ```bash
> uv pip install -e '.[llm]'
> export ANTHROPIC_API_KEY=sk-ant-...
> # puis utiliser --config ~/.goal/config.toml
> ```

## Configuration TOML

Si `~/.goal/config.toml` existe, `goal run` l'utilise pour résoudre les providers par rôle, le budget, le rate limit et le cache. Sinon, le mode CLI historique (`--provider mock|kimi-cli|kimi-code`) reste disponible.

```toml
[providers]
enabled = ["anthropic", "openai", "google"]
role_mapping = { producer = "anthropic", critic = "openai", adversary = "google", arbiter = "google" }
synthesizer = "anthropic"
require_diversity = false

[ratelimit]
max_retries = 3
initial_backoff_s = 1.0
backoff_multiplier = 2.0

[budget]
max_per_run_usd = 0.50
max_per_day_usd = 10.00
warn_at_percent = 80
hard_stop = true
runs_per_day_projection = 10

[cache]
provider = "exact"
enable_semantic = false
ttl_seconds = 3600

[logging]
level = "INFO"
format = "structlog"
```

Règles de validation :

- **Diversité** : `require_diversity = true` refuse tout mode dégradé. La CLI refuse aussi de démarrer si tous les rôles résolvent vers la même famille de provider.
- **Rate limit** : `[ratelimit]` (canonique) ou `[rate_limit]` (alias historique).
- **Secrets** : ne JAMAIS mettre de clé API dans `config.toml`. Utiliser les variables d'environnement des SDKs (`ANTHROPIC_API_KEY`, etc.).

## Sécurité

Le projet applique une grille de sécurité issue des audits A-F (cahier de tests `tests/test_*_security.py`) :

| Audit | Critère | Implémentation |
|---|---|---|
| A1-A6 | Hook CI/CD déterministe | `src/goal_cascade/orchestrator/cicd_hook.py`, câblé dans `cascade_executor` après chaque synthèse. Pas de `shell=True`, timeout 30s, contenu passé par stdin/tempfile, jamais dans la commande. |
| B1-B5 | PromptLoader durci | Pas de traversal (`..`, `/`), Jinja2 sandbox, PromptNotFoundError explicite, hiérarchie projet > user > package. |
| C1-C6 | MultiCascadeExecutor | Validation acyclicité, budget par module, arrêts propres, parallélisme contrôlé (synchrone v1), contrats vérifiés après chaque batch. |
| E1 | Pas de secrets dans les logs | `redact_sensitive()` masque Bearer, api_key, password, tokens avant toute persistance. |
| E2 | Traces isolées | `~/.goal/runs/<run_id>/` permissions `0o700` (garanti au démarrage du module). |
| E3 | Cache sémantique local | `Path.home() / ".goal" / "semantic_cache.db"` permissions `0o700`. |
| E4 | `.gitignore` complet | `.goal/runs/`, `.goal/semantic_cache.db`, `.goal/checkpoints.db`, `.goal/budget_daily.json`. |
| F1 | Pas de cache sémantique intra-cascade | `SemanticCache.lookup()` jamais appelé dans `CascadeExecutor` ni `Synthesizer.process()`. |
| F2 | Historique brut jamais transmis | Templates utilisent `last_synthesis` (mode normal), `previous_output` uniquement en `--no-synth`. |
| F3 | Limite absolue 5 itérations | `max_iterations=5` enforced dans `_run_loop`. |
| F4 | STOP par défaut | `_parse_verdict` catch → verdict STOP automatique, jamais `failed` silencieux. |
| F5 | Diversité providers validée | CLI refuse de démarrer si tous les rôles → même famille (hors `mock`). |

## Transparence des coûts

Chaque run produit `<run_dir>/receipt.json` :

- `total_cost_usd` : somme des coûts de tous les appels LLM.
- `cache_hit_rate` : `cache_read_tokens / total_input_tokens`.
- `projected_monthly_cost` : projection basée sur `runs_per_day_projection`.
- `calls` : liste complète des `LLMCallRecord` (input/output tokens, cost, latency).
- `final_verdict` : `STOP` / `CONTINUE` / `absent`.
- `total_duration_s`.

### Kill switch budgétaire

Quand `hard_stop=true` et que le coût courant dépasse `max_per_run_usd` (ou le cumul journalier dépasse `max_per_day_usd`), la cascade s'arrête avec statut `budget_exceeded`. Le reçu final est conservé. Le cumul quotidien est dans `<GOAL_HOME>/budget_daily.json` (permissions `0o600`).

## Traçabilité permanente

Chaque run est conservé sous `~/.goal/runs/<run_id>/` (permissions `0o700`). Le dossier contient :

- `events.jsonl` : événements append-only horodatés et numérotés.
- `prompt_<iteration>_<role>.txt` : chaque prompt envoyé.
- `iteration_<n>.txt` et `synthesis_<n>.json` : résultats bruts.
- `state.json` et `final_output.md` : état et livrable.
- `timeline.md` : manifeste humain pour le RAG.
- `rag-status.json` : reçu observable d'indexation + embedding.
- `receipt.json` : transparence des coûts.

## RAG PostgreSQL et embeddings

À chaque run, `timeline.md` est indexé dans la catégorie PostgreSQL `goal-cascade`. Les embeddings sont demandés à `ia-general` (`localhost:11434`) avec `bge-m3:latest` (dimension 1024).

```bash
goal rag-status <run_id>
goal rag-sync <run_id>
```

Statuts possibles : `pending`, `indexing`, `indexed_pending_embedding`, `embedded`, `failed`. Une indisponibilité d'`ia-general` reste enregistrée et n'est jamais transformée en faux succès.

Variables d'environnement :

| Variable | Défaut | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | URL Ollama |
| `OLLAMA_EMBED_URL` | `$OLLAMA_HOST/api/embed` | Endpoint embeddings |
| `OLLAMA_EMBED_MODEL` | `bge-m3:latest` | Modèle |

## Tests

```bash
# Suite complète (282 tests, 4 skip)
uv run pytest -p no:cacheprovider -q

# Tests d'intégration avec un vrai provider LLM
GOAL_RUN_INTEGRATION=1 \
GOAL_INTEGRATION_PROVIDER=anthropic \
ANTHROPIC_API_KEY=sk-ant-... \
uv run pytest -p no:cacheprovider tests/integration/test_real_provider_smoke.py -v
```

Le smoke test vrai provider est skip par défaut pour éviter les coûts accidentels en CI.

## Exemples

```bash
# Mock local (zéro coût, zéro dépendance)
uv run goal run --objective "Auditer un argument" --variant A --provider mock

# Kimi CLI non interactif (sessions jetables)
uv run goal run --objective "Auditer un argument" --variant A \
  --provider kimi-cli --synthesizer-model "moonshot/kimi-k2-0711-preview"

# Vrai provider avec config TOML
uv run goal run --objective "Refactor ce module" --variant B --config ~/.goal/config.toml

# Multi-cascade avec enrichissement LLM
uv run goal plan spec.md --enrich-frozen-specs --output plan.json
uv run goal cascade-run plan.json
```

## Licence

MIT — voir `LICENSE`.