# ADR-001 : Modèle d'embedding — bge-m3 (local Ollama) vs OpenAI text-embedding-3

> **Statut** : Accepté · **Date** : 2026-07-15 · **Décideurs** : Eddie

## Contexte

La spec d'implémentation V2 §5.3 prescrivait :

> *"Règle d'embedding unifié : utiliser un seul modèle d'embedding (OpenAI `text-embedding-3`) pour tous les calculs de similarité, indépendamment du provider de la cascade. Évite les incohérences entre providers."*

L'implémentation effective utilise **bge-m3:latest** (1024 dimensions) servi par Ollama local (`localhost:11434`) pour TOUS les calculs d'embedding :
- Détection de dérive cosinus (`src/goal_cascade/orchestrator/drift_detector.py`)
- Indexation RAG PostgreSQL (`src/goal_cascade/rag/embed.py`)

## Décision

**Utiliser bge-m3:latest via Ollama local comme unique modèle d'embedding.**

L'esprit de la règle spec ("un seul modèle pour toutes les mesures") est respecté : drift et RAG utilisent le même modèle, donc les similarités sont comparables. Seule la lettre ("OpenAI") diffère.

## Alternatives considérées

| Option | Coût | Privacy | Setup | Conformité spec | Verdict |
|---|---|---|---|---|---|
| OpenAI `text-embedding-3` (spec) | ~$0.02/1M tok | Données envoyées à OpenAI | Clé API | ✅ 100% | Rejeté |
| **bge-m3 via Ollama local** (retenu) | $0 | 100% local | Ollama + `bge-m3:latest` | ⚠️ Esprit OK | **Retenu** |
| sentence-transformers Python | $0 | 100% local | `pip install` + modèle | ⚠️ Esprit OK | Rejeté |
| Cohere `embed-multilingual-v3` | ~$0.10/1M tok | Cloud externe | Clé API | ❌ | Rejeté |

## Conséquences

### Positives

- **Coût nul** : Ollama + bge-m3 sont gratuits, pas d'API payante à l'usage.
- **Privacy** : les sorties de cascade (potentiellement sensibles) ne quittent jamais la machine. Important pour un outil qui peut traiter des données métier.
- **Latence locale** : pas de RTT réseau vers OpenAI (~50-200 ms économisés par appel d'embedding).
- **Cohérence** : le même modèle est utilisé pour drift ET RAG, donc les distances sont comparables. La règle spec "un seul modèle" est respectée en esprit.
- **Pas de dépendance externe critique** : pas de rate-limit API OpenAI, pas de risque de quota épuisé en pleine cascade.

### Négatives

- **Setup local plus lourd** : l'utilisateur doit installer Ollama (`curl -fsSL https://ollama.com/install.sh | sh`) puis tirer le modèle (`ollama pull bge-m3:latest`).
- **Performance machine** : bge-m3 nécessite ~4 GB RAM. Sur machine peu puissante, l'embedding peut être plus lent que l'API OpenAI.
- **Conformité spec à 80%** : la lettre de la spec n'est pas respectée. Toute évolution future de bge-m3 peut casser la cohérence.

### Mitigations

| Risque | Mitigation |
|---|---|
| Setup local complexe | Documentation dans README §"Configuration Ollama" |
| Performance | Drift timeout à 2s (`DRIFT_TIMEOUT_S`), dégradation gracieuse si timeout |
| Évolution modèle | Embedding versionné dans le reçu (`receipt.json`) |

## Conséquences pour le code

### Fichiers impactés

- `src/goal_cascade/orchestrator/drift_detector.py` — utilise `OllamaEmbedding(bge-m3:latest, timeout=DRIFT_TIMEOUT_S)`
- `src/goal_cascade/rag/embed.py` — module d'embeddings Ollama
- `src/goal_cascade/rag/__init__.py` — exposer `default_ollama_embed_model()` qui retourne `"bge-m3:latest"`

### Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | URL du serveur Ollama |
| `OLLAMA_EMBED_URL` | `$OLLAMA_HOST/api/embed` | Endpoint embeddings |
| `OLLAMA_EMBED_MODEL` | `bge-m3:latest` | Modèle d'embedding |

### Dégradation gracieuse

Si l'embedding échoue (timeout, Ollama down), `DriftDetector.evaluate()` retourne `DriftStatus.ERROR` au lieu de planter la cascade. La cascade continue sans détection de dérive, avec un warning dans le journal.

## Réversibilité

Pour revenir à OpenAI `text-embedding-3` si nécessaire :
1. Créer une classe `OpenAIEmbedding` dans `src/goal_cascade/rag/embed.py`
2. Modifier `OllamaEmbedding` → `BaseEmbedding` interface
3. Ajouter une variable d'environnement `EMBEDDING_PROVIDER=ollama|openai`
4. Mettre à jour le reçu pour enregistrer le provider utilisé

Effort estimé : 2-3 heures. Non justifié à ce stade.

## Validation

| Critère | Statut |
|---|---|
| Embedding fonctionne via Ollama local | ✅ `drift_detector.py` opérationnel |
| Modèle unique pour drift + RAG | ✅ bge-m3 partout |
| Setup documenté pour l'utilisateur | ✅ README §"Configuration Ollama" |
| Dégradation gracieuse si échec | ✅ `DriftStatus.ERROR` |
| Dimensions documentées | ✅ 1024D |

## Liens

- Spec V2 §5.3 — exigence originale (lettre)
- `docs/superpowers/specs/2026-07-11-rag-worker-env-design.md` — design connexe sur l'infra RAG
- `src/goal_cascade/orchestrator/drift_detector.py` — implémentation
- `src/goal_cascade/rag/embed.py` — embeddings Ollama

## Notes de revue

- Revue initiale (2026-07-15) : cette ADR formalise le choix déjà implémenté. Aucune migration n'est nécessaire — juste la documentation.
- Les divergences D1 (modèle) et A1 (suppression `_run_loop`) ont été soldées en parallèle dans la même session.
