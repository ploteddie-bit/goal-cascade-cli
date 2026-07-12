# Changelog

Toutes les modifications notables de `goal-cascade-cli` sont documentées ici. Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/), et le projet adhère au [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — 2026-07-12

### Ajouté

- **S6 Multi-cascade** : `goal plan` génère un plan JSON depuis un spec ; `goal cascade-run` exécute toutes les cascades d'un plan via un exécuteur topologique networkx. Commande `goal cascade-run` câblée avec budget tracker et `MultiCascadeExecutor`.
- **S6 Enrichissement LLM opt-in** : option `--enrich-frozen-specs` sur `goal plan`. Génère 3–5 invariants supplémentaires via `prompts/frozen_spec_gen.j2`. Tous les invariants `llm-generated` restent `verified=False` — validation humaine obligatoire avant `goal cascade run`.
- **S6 Hook CI/CD déterministe** câblé dans `CascadeExecutor` (cascade unique) : vérification syntaxique Python (`py_compile`) + JSON (`json.tool`) après chaque synthèse. Mode informatif (n'interrompt pas la cascade).
- **Sécurité E1–E4** : `redact_sensitive` pour les logs, `~/.goal/runs/` forcé en `0o700` à l'init du module, `budget_daily.json` en `0o600`, `.gitignore` complet.
- **Sécurité F1–F5** : `cascade_executor._parse_verdict` retourne STOP par défaut sur JSON invalide (doute profite au STOP), CLI refuse de démarrer si tous les rôles → même famille de provider (Pilier 1 diversity).
- **Audit trail A1–A6** sur le hook CI/CD : timeout 30s, pas de `shell=True`, contenu passé par stdin/tempfile, jamais interpolé dans une commande.
- **Nouveau champ `source`** sur `Invariant` (`manual | auto-from-planning | llm-generated`) pour tracer la provenance.
- **Tests d'intégration** : `tests/integration/test_goal_run_smoke.py` (mock-based, toujours actif) + `tests/integration/test_real_provider_smoke.py` (vrai provider, skip par défaut, activable via `GOAL_RUN_INTEGRATION=1`).

### Modifié

- **README.md** : réécrit pour refléter l'état S1–S6 + section Security complète. Suppression du disclaimer « fondation partielle ».
- **Cascade unique** : `CICDHook` désormais invoqué après chaque synthèse (auparavant absent).

### Sécurité

- 10 tests `tests/test_data_confidentiality.py` + 3 tests `tests/test_cascade_cicd_wiring.py` + 4 tests `tests/test_*_security.py`.
- 273 tests passent, 1 skip (intégration vrai provider).

## [0.2.0] — 2026-07-08

### Ajouté

- **S4 LangGraph + budget** : graphe d'états à 6 nœuds (INIT → PRODUCER → SYNTH → CRITIC → SYNTH → ADVERSARY → SYNTH → ARBITER → VERDICT), checkpoints SQLite via `langgraph-checkpoint-sqlite`. Commande `goal resume <run_id>`.
- **Kill switch budgétaire** : section `[budget]` TOML avec `max_per_run_usd`, `max_per_day_usd`, `hard_stop`. Statut `budget_exceeded` + verdict STOP explicite.
- **S2 Multi-provider réel** : `anthropic`, `openai`, `google` via Mirascope v2 (`pip install '.[llm]'`). Chaîne de fallback respectant la diversité de familles (Pilier 1) via `PROVIDER_FAMILIES`.
- **S2 Rate limit** : `RateLimitConfig` configurable via `[ratelimit]` TOML (max_retries, initial_backoff_s, backoff_multiplier). Backoff exponentiel puis bascule fallback.
- **S3 Détection de dérive** : `DriftDetector` (similarité cosinus `bge-m3:latest` 1024D). Stop forcé si dérive critique.
- **S3 Mode `--no-synth`** : debug, sortie brute passée telle quelle.
- **S5 Cache sémantique** : `SemanticCache` SQLite local, jamais appelé intra-cascade.
- **S5 Versioning** : `goal versions`, `goal diff`, `goal inspect`. Schemas `RunVersion`, `VersionDiff`, `RunVersionsList`.
- **Receipt détaillé** : `<run_dir>/receipt.json` avec `total_cost_usd`, `cache_hit_rate`, `projected_monthly_cost`, `calls[]`, `final_verdict`, `total_duration_s`.
- **RAG bridge** : `goal rag-sync <run_id>` vers PostgreSQL catégorie `goal-cascade` + embeddings `ia-general`.

### Modifié

- **Providers CLI Kimi** : nouveau séparateur strict `synthesizer_provider is provider` → `ValueError` si partagé (anti-régression).

## [0.1.0] — 2026-07-04

### Ajouté

- **Cascade unique** : 4 rôles (producteur, critique, adversaire, arbitre), synthèse orientée objectif entre les rôles, préservation des blocs de code (artefacts immuables), verdict JSON validé par Pydantic (`STOP` ou `CONTINUE`), borne stricte de 5 itérations.
- **Providers** : `MockProvider`, `KimiCommandProvider` (CLI 1.x et Code 0.x).
- **Prompts** : 9 templates Jinja2 (A rédactionnel + B technique × 4 rôles + synthesis).
- **Traçabilité** : `~/.goal/runs/<run_id>/` avec `events.jsonl`, `timeline.md`, `state.json`, `final_output.md`.

## Notes de versionnage

- Le projet est en **pre-1.0**. Les versions mineures (0.x.0) peuvent contenir des changements incompatibles avec le plan JSON ou les contrats d'interface. À partir de 1.0.0, le format `plan.json` et les `FrozenSpec` seront stables.
- Le numéro de version suit `pyproject.toml` ([project] version).