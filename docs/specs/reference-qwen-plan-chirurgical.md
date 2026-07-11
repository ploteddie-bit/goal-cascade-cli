 G.O.A.L. Cascade CLI — Plan Chirurgical d'Exécution

## Métadonnées

| Champ | Valeur |
|-------|--------|
| **Projet** | CLI open-source pour le framework G.O.A.L. Cascade |
| **Version** | 1.0 — Plan d'architecture |
| **Date** | Juillet 2026 |
| **Auteur** | Eddie |
| **Statut** | Prêt pour implémentation |
| **Durée estimée** | 6 semaines (1 dev senior) ou 10 semaines (1 dev junior) |
| **Objectif** | Produire un CLI qui exécute des cascades G.O.A.L. avec transparence totale des coûts, détection de dérive, et multi-provider structuré |

---

## TL;DR — La décision architecturale

**Stack retenue :**
- **Langage** : Python 3.11+ (pas Go)
- **CLI** : Typer (minimal, type-safe)
- **Multi-provider** : Mirascope (API unifiée Anthropic/OpenAI/Google)
- **State machine** : LangGraph (branching STOP/CONTINUE + checkpointing natif)
- **Validation** : Pydantic v2 (artefacts immuables typés)
- **Persistance** : SQLite (checkpoints + cache sémantique)
- **Distribution** : pipx (installation globale isolée)

**Principe directeur :** Le CLI n'est pas un chat augmenté. C'est une **pipeline déterministe à états** avec transparence radicale des coûts.

---

## 1. Architecture Cible

### 1.1 Vue d'ensemble des composants

```
+--------------------------------------------------------------+
|                    CLI (Typer)                               |
|  goal run <objective>                                        |
|  goal cascade plan <spec>                                    |
|  goal resume <run_id>                                        |
|  goal status <run_id>                                        |
+----------------------------+---------------------------------+
                             |
+----------------------------v---------------------------------+
|              ORCHESTRATEUR G.O.A.L.                          |
|  +--------------------------------------------------------+  |
|  |  Synthesizer       |  Drift detector (cos sim)         |  |
|  |  Verdict STOP      |  Frozen spec validator            |  |
|  |  Q(T) tracker      |  Immutable payload handler        |  |
|  +--------------------------------------------------------+  |
+--------------------------------------------------------------+
|  LangGraph (state machine + branching + checkpointing)       |
+--------------------------------------------------------------+
|  Mirascope (multi-provider unifié + cache exact)             |
|  Anthropic <-> OpenAI <-> Google                             |
+--------------------------------------------------------------+
```

### 1.2 Les 3 couches de valeur (ce que tu possèdes vs ce que tu délègues)

| Couche | Ce que tu construis (propriété intellectuelle) | Ce que tu délègues (plomberie) |
|--------|------------------------------------------------|--------------------------------|
| **Logique métier** | Synthesizer orienté objectif, drift detection, verdicts STOP/CONTINUE, frozen spec validator, Q(T) tracker | — |
| **Orchestration** | Graphe d'états G.O.A.L., branching conditionnel, checkpointing | LangGraph (state machine + SQLite natif) |
| **Multi-provider** | Règle de diversité stricte, cache exact activé, rotation des providers | Mirascope (API unifiée) |

**Règle absolue :** Si tu délègues la logique métier (synthesizer, drift, verdicts), tu perds la valeur du framework. Cette couche doit être 100% maison.

---

## 2. Pourquoi Python et pas Go

### 2.1 L'incompatibilité fondamentale

| Composant | Langage disponible |
|-----------|-------------------|
| Mirascope | Python uniquement |
| LangGraph | Python uniquement |
| CLI Go (Cobra) | Go uniquement |

**Tu ne peux pas combiner les trois nativement.** Les options pour les faire coexister :
- Serveur Python (FastAPI) + client Go → complexité réseau, latence, serialization
- CGO/FFI → fragile, pénible à maintenir
- Abandonner Mirascope/LangGraph → tout refaire en Go (10+ semaines)

### 2.2 La décision : tout Python

**Avantages :**
- Cohérence totale de la stack
- POC en 6 semaines (vs 10+ en Go)
- Mirascope/LangGraph utilisés nativement
- Même langage que la recherche (tous les papers sont en Python)
- Facile de recruter/contribuer

**Inconvénients (mineurs) :**
- Moins rapide que Go (peu critique pour un CLI IA)
- Binary distribuable via PyInstaller (pas natif)
- Plus de dépendances Python

**Verdict :** La valeur du framework est dans la logique métier (synthesizer, drift, Q(T)), pas dans la performance du CLI. Python est le choix rationnel.

---

## 3. Les Outils — Justification et Alternatives

### 3.1 Tableau de décision des outils

| Outil | Rôle | Justification | Alternative rejetée | Raison du rejet |
|-------|------|---------------|---------------------|-----------------|
| **Typer** | CLI framework | Simple, type-safe, auto-génération help | Click | Plus verbeux, moins moderne |
| **Mirascope** | Multi-provider | API unifiée Anthropic/OpenAI/Google, pydantic-first | LiteLLM | Moins type-safe, API moins propre |
| **LangGraph** | State machine | Branching STOP/CONTINUE natif + checkpointing SQLite gratuit | State machine maison | 3+ semaines de dev pour refaire ce qui existe |
| **Pydantic v2** | Validation | Typage strict des artefacts immuables, sérialisation | dataclasses | Pas de validation runtime, pas de JSON schema auto |
| **SQLite** | Persistance | Checkpoints + cache sémantique, zéro config | PostgreSQL | Overkill pour un CLI local |
| **structlog** | Logging | Logs structurés, debuggable | logging standard | Pas de structure, pas de contexte |
| **TOML** | Config | Standard Python moderne, lisible | YAML | Moins strict, parsing ambigu |
| **pytest** | Tests | Standard, async natif | unittest | Plus verbeux, moins de features |
| **pipx** | Distribution | Installation globale isolée | pip install | Pollution de l'environnement global |

### 3.2 Ce que tu n'utilises PAS (et pourquoi)

| Outil tentant | Pourquoi tu le rejettes |
|---------------|-------------------------|
| **LangChain** | Overhead, abstractions inutiles pour ton cas |
| **Redis** | Overkill pour un CLI local, SQLite suffit |
| **Docker** | Pas nécessaire pour un CLI Python installable |
| **FastAPI** | Tu n'as pas besoin d'un serveur, juste un CLI |
| **OpenTelemetry** | Overkill pour un projet solo/petite équipe |

---

## 4. Plan d'Exécution — 6 Semaines

### 4.1 Vue d'ensemble des phases

```
Semaine 1 → Fondations + single cascade minimale
Semaine 2 → Multi-provider + Mirascope
Semaine 3 → Synthesizer + artefacts immuables
Semaine 4 → LangGraph state machine + branching
Semaine 5 → Détection de dérive + cache sémantique
Semaine 6 → Multi-cascade + intégration
```

### 4.2 Détail par semaine

#### Semaine 1 — Fondations + single cascade minimale

**Objectif :** Un CLI qui exécute 1 cascade de 4 itérations sur un seul provider, sans optimisation.

**Livrables :**
- Projet Python avec `pyproject.toml` (uv), structure modulaire
- CLI avec Typer : commandes `goal init`, `goal run`, `goal status`
- 4 prompts du framework en templates Jinja2
- Exécuteur linéaire : Itération 1 → 2 → 3 → 4 (sans branching)
- State persisté dans `~/.goal/runs/<run_id>.json`
- 1 provider intégré (Anthropic, via Mirascope)

**Critère de succès :** `goal run --objective "..."` produit un livrable final après 4 itérations.

**Piège à éviter :** Ne pas chercher le multi-provider cette semaine. Un seul provider, mais la structure doit être propre.

**Temps estimé :** 15-20 heures

---

#### Semaine 2 — Multi-provider + Mirascope

**Objectif :** Exploiter le Pilier 1 (diversité multi-provider) avec Mirascope.

**Livrables :**
- Intégration Mirascope pour Anthropic + OpenAI + Google
- Validation au démarrage : refuse un run si les 4 modèles viennent du même provider
- Configuration des 4 tiers (petit/moyen/grand/très grand) dans `~/.goal/config.toml`
- Activation du cache exact Anthropic (via `cache_control`)
- Logging structuré (structlog) : chaque appel LLM loggué

**Critère de succès :** Un run utilise 4 providers différents. La config est rejetée si non conforme.

**Piège à éviter :** Ne pas multiplier les abstractions prématurément. Mirascope offre déjà une API unifiée.

**Temps estimé :** 12-15 heures

---

#### Semaine 3 — Synthesizer + artefacts immuables

**Objectif :** Implémenter la pièce maîtresse (Section 4 du framework) — la couche qui distingue G.O.A.L. de tous les autres outils.

**Livrables :**
- Synthesizer pipeline : prompt dédié + validation de sortie
- Schema Pydantic pour les 4 blocs (Objectif / Décisions / Incertitudes / Instruction)
- Charge utile immuable : type `ImmutablePayload` pour code/JSON/formules
- Validation automatique : rejette une synthèse qui dépasse 5 décisions clés
- Mode `--no-synth` pour debug

**Critère de succès :** Entre chaque itération, le prompt reçu contient uniquement les 4 blocs + artefacts immuables, jamais l'historique brut.

**Piège à éviter :** Ne pas laisser le LLM de synthèse "tricher". Valider avec Pydantic, pas avec le LLM.

**Temps estimé :** 15-20 heures

---

#### Semaine 4 — LangGraph state machine + branching STOP/CONTINUE

**Objectif :** Implémenter le Pilier 3 (boucles bornées, Q(T)) avec une vraie state machine.

**Livrables :**
- Graphe LangGraph : nœuds `producer`, `synthesizer`, `critic`, `adversary`, `arbitrator`
- Edge conditionnelle : verdict route vers STOP ou CONTINUE
- Compteur d'itérations + STOP forcé à 5 itérations
- Checkpointing SQLite natif LangGraph
- Commande `goal resume <run_id>` pour relancer un run interrompu

**Critère de succès :** `goal run` produit soit un STOP à itération 4, soit un rebouclage vers 5, jamais au-delà.

**Piège à éviter :** Ne pas coder ta propre state machine. LangGraph est fait pour ça.

**Temps estimé :** 15-20 heures

---

#### Semaine 5 — Détection de dérive + cache sémantique

**Objectif :** La feature la plus novatrice — utiliser la similarité cosinus pour détecter que la cascade tourne à vide.

**Livrables :**
- Génération d'embeddings pour chaque sortie d'itération
- Calcul de similarité cosinus entre sorties N et N+1
- Alertes selon les seuils (≥0.95 = STOP anticipé)
- Dashboard minimal dans `goal status` : graphique ASCII
- Cache sémantique entre runs (SQLite + embeddings)

**Critère de succès :** `goal status` affiche la "vitesse" de la cascade. Un run qui stagne est stoppé automatiquement.

**Piège à éviter :** Ne pas calibrer les seuils à la main sur chaque run. Fournis des seuils par défaut documentés.

**Temps estimé :** 12-15 heures

---

#### Semaine 6 — Multi-cascade + intégration

**Objectif :** Implémenter le guide multi-cascade — la phase de découpage modulaire.

**Livrables :**
- Commande `goal cascade plan <spec.md>` → génère un `plan.json`
- Exécuteur topologique : produit les feuilles en parallèle
- Hard Gate : validation déterministe des contrats d'interface
- Soft Gate : LLM ne vérifie que la sémantique métier
- Commande `goal cascade run <plan.json>` → exécute N cascades parallèles
- Cascade d'intégration (Phase 5) : assembleur + adversaire système + arbitre global

**Critère de succès :** `goal cascade run` produit un livrable > 10 000 lignes avec la même qualité qu'un livrable de 500 lignes.

**Piège à éviter :** Ne pas lancer toutes les cascades en parallèle sans respecter le graphe topologique.

**Temps estimé :** 20-25 heures

---

### 4.3 Récapitulatif des temps

| Semaine | Heures estimées | Cumul |
|---------|-----------------|-------|
| 1 | 15-20 | 15-20 |
| 2 | 12-15 | 27-35 |
| 3 | 15-20 | 42-55 |
| 4 | 15-20 | 57-75 |
| 5 | 12-15 | 69-90 |
| 6 | 20-25 | 89-115 |
| **Total** | **89-115 heures** | — |

**En semaines (1 dev senior à temps plein) :** ~6 semaines  
**En semaines (1 dev junior à temps plein) :** ~10 semaines  
**En semaines (temps partiel, 10h/semaine) :** ~9-12 semaines

---

## 5. Les Garde-Fous — Transparence Radicale

### 5.1 Le principe architectural : chaque run produit un reçu

**Règle absolue :** Le CLI doit traiter la transparence des coûts comme un principe architectural au même titre que la synthèse orientée objectif.

**Chaque appel LLM doit capturer :**
- `input_tokens`
- `output_tokens`
- `cache_read_input_tokens`
- `cost` (calculé selon les tarifs publics du provider)

**À la fin de chaque run, le CLI affiche :**
- Nombre d'itérations et verdict final
- Durée totale du run
- Tableau détaillé par étape (Input, Output, Cache, Coût)
- Taux de hit du cache
- Projection mensuelle basée sur 10 runs/jour

### 5.2 Le Kill Switch budgétaire

**Dans `~/.goal/config.toml` :**

```toml
[budget]
max_per_run = 0.50
max_per_day = 10.00
warn_at_percent = 80
hard_stop = true
```

**Dans le code :** Une exception `BudgetExceeded` est levée quand le budget est atteint, avec message explicite et instruction de reprise.

### 5.3 Comment G.O.A.L. réduit mécaniquement les coûts

| Levier | Mécanisme | Économie |
|--------|-----------|----------|
| Synthèse orientée objectif | Input de l'étape N+1 = ~300 tokens, pas ~5000 | **-80% sur les inputs** |
| Cache exact sur préfixe stable | Objectif + Frozen Spec = ~1200 tokens identiques | **-90% sur le préfixe** |
| Charge utile immuable | Code transmis en bloc, pas re-tokenisé | **-30% sur les tokens de code** |
| STOP par défaut | Pas de boucle infinie "juste une de plus" | **Élimine les 20% de runs qui coûtent 3x** |
| Cascade ascendante | Iter 1 = petit modèle ($0.001/1K tokens) | **-70% sur l'itération 1** |

**Coût réel d'un run G.O.A.L. optimisé :**
- Sans G.O.A.L. (single model, historique brut, 5 itérations) : ~50K tokens → ~$0.75
- Avec G.O.A.L. (synthèse + cache + cascade ascendante, 4 itérations) : ~8K tokens → ~$0.08

**Un run optimisé coûte 10x moins cher qu'un run naïf.**

---

## 6. Les Décisions Architecturales Clés

### 6.1 Tableau de décision

| Décision | Choix retenu | Justification | Alternative rejetée |
|----------|--------------|---------------|---------------------|
| Langage | Python | Mirascope/LangGraph natifs, écosystème IA | Go (incompatible) |
| CLI framework | Typer | Simple, type-safe | Click (plus verbeux) |
| Multi-provider | Mirascope | API unifiée, pydantic-first | LiteLLM (moins type-safe) |
| State machine | LangGraph | Branching + checkpointing natifs | Maison (3+ semaines) |
| Validation | Pydantic v2 | Typage strict, JSON schema auto | dataclasses (pas de validation) |
| Persistance | SQLite | Zéro config, checkpoints natifs | PostgreSQL (overkill) |
| Config | TOML | Standard Python moderne | YAML (moins strict) |
| Distribution | pipx | Installation globale isolée | pip install (pollution) |
| Logging | structlog | Structuré, debuggable | logging standard (pas de structure) |
| Tests | pytest | Standard, async natif | unittest (plus verbeux) |

### 6.2 Les NON-décisions (ce que tu ne fais PAS)

| Tentation | Pourquoi tu refuses |
|-----------|---------------------|
| LangChain | Overhead, abstractions inutiles |
| Redis | Overkill pour un CLI local |
| Docker | Pas nécessaire pour un CLI Python |
| FastAPI | Tu n'as pas besoin d'un serveur |
| OpenTelemetry | Overkill pour un projet solo |
| Cache sémantique intra-cascade | Tue la diversité multi-provider |
| Multi-cascade avant Semaine 6 | Maîtrise d'abord la cascade simple |

---

## 7. Livrables Finaux (Semaine 6)

### 7.1 Ce que tu livres

| Livrable | Description |
|----------|-------------|
| `goal` (CLI) | Binaire Python installable via `pipx install goal-cascade` |
| Documentation | README + guide d'usage + référence des commandes |
| Templates Jinja | Tous les prompts du framework, customisables |
| Config d'exemple | `~/.goal/config.toml` avec providers + modèles |
| 3 cas d'usage | Article LinkedIn / fonction Python / mini-app multi-modules |
| Benchmarks | Coût, latence, qualité vs baseline single-model |
| Tests | Tests unitaires (synthesizer, drift) + tests d'intégration |

### 7.2 Ce que tu ne livres PAS (périmètre exclu)

| Exclusion | Justification |
|-----------|---------------|
| Interface graphique | CLI uniquement (scope du projet) |
| Support de providers exotiques | Anthropic/OpenAI/Google uniquement |
| Orchestration cloud (Kubernetes) | CLI local uniquement |
| Multi-utilisateurs / authentification | Usage solo/équipe restreinte |
| Intégration IDE (VS Code plugin) | Scope futur, pas v1 |

---

## 8. Checklists de Production

### 8.1 Checklist pré-démarrage

- [ ] Python 3.11+ installé
- [ ] uv installé (gestionnaire de paquets moderne)
- [ ] Compte Anthropic créé + clé API
- [ ] Compte OpenAI créé + clé API
- [ ] Compte Google AI créé + clé API
- [ ] Git configuré
- [ ] Éditeur de code configuré (VS Code / PyCharm)
- [ ] Temps disponible : 6 semaines × 15h/semaine minimum

### 8.2 Checklist par semaine

**Semaine 1 :**
- [ ] Structure projet créée (`pyproject.toml`, dossiers)
- [ ] CLI Typer fonctionnel (`goal run` exécute)
- [ ] 4 prompts intégrés en templates Jinja
- [ ] Exécuteur linéaire fonctionne (4 itérations)
- [ ] State persisté en JSON
- [ ] 1 provider intégré (Anthropic)

**Semaine 2 :**
- [ ] Mirascope intégré pour 3 providers
- [ ] Validation diversité providers active
- [ ] Config TOML fonctionnelle
- [ ] Cache exact Anthropic activé
- [ ] Logging structlog en place

**Semaine 3 :**
- [ ] Synthesizer pipeline fonctionnel
- [ ] Schema Pydantic pour 4 blocs
- [ ] Charge utile immuable typée
- [ ] Validation synthèse automatique
- [ ] Mode `--no-synth` disponible

**Semaine 4 :**
- [ ] Graphe LangGraph créé
- [ ] Branching STOP/CONTINUE fonctionnel
- [ ] STOP forcé à 5 itérations
- [ ] Checkpointing SQLite actif
- [ ] Commande `goal resume` fonctionne

**Semaine 5 :**
- [ ] Embeddings générés pour chaque sortie
- [ ] Similarité cosinus calculée
- [ ] Alertes dérive actives
- [ ] Dashboard ASCII dans `goal status`
- [ ] Cache sémantique inter-runs actif

**Semaine 6 :**
- [ ] Commande `goal cascade plan` fonctionnelle
- [ ] Exécuteur topologique actif
- [ ] Hard Gate (validation déterministe) actif
- [ ] Soft Gate (validation LLM sémantique) actif
- [ ] Commande `goal cascade run` fonctionnelle
- [ ] Cascade d'intégration (Phase 5) active

### 8.3 Checklist post-production (avant release)

- [ ] Documentation README complète
- [ ] Guide d'usage rédigé
- [ ] 3 cas d'usage testés et documentés
- [ ] Benchmarks coût/latence/qualité publiés
- [ ] Tests unitaires > 80% de couverture
- [ ] Tests d'intégration (cascade complète) passent
- [ ] Package publié sur PyPI
- [ ] Installation via pipx testée
- [ ] Licence MIT ajoutée
- [ ] CHANGELOG initialisé

---

## 9. Anti-Patterns à Éviter

### 9.1 Tableau des pièges

| Anti-pattern | Symptôme | Cause | Parade |
|--------------|----------|-------|--------|
| Abstraction prématurée | Code complexe, difficile à debug | Vouloir tout généraliser trop tôt | YAGNI — construis seulement ce dont tu as besoin |
| State machine maison | 3+ semaines perdues | Refuser d'utiliser LangGraph | Utilise LangGraph, il est fait pour ça |
| Cache sémantique intra-cascade | Qualité dégradée, diversité tuée | Vouloir "aller plus vite" | Cache exact dedans, sémantique dehors |
| Pas de tracking de coûts | Budget explose sans explication | Oublier la transparence | Reçu détaillé à chaque run |
| Multi-cascade trop tôt | Cascade simple ne fonctionne pas | Vouloir tout faire d'un coup | Maîtrise la cascade simple avant |
| Pas de kill switch budgétaire | Runs infinis, facture surprise | Pas de garde-fou | Budget max par run + hard stop |
| Historique brut transmis | Ancrage, context rot, Woozle | Pas de synthèse | Synthèse orientée objectif obligatoire |
| Fausse diversité providers | Erreurs corrélées, pas de valeur | 2 modèles du même provider | Règle de diversité stricte (3+ providers) |

### 9.2 Les 3 erreurs fatales

1. **Forker un CLI existant (aider, claude-code, kimi-code)**
   - Tu paierais la dette d'autrui + ta propre dette
   - Leurs paradigmes (chat augmenté) contredisent ta vision (pipeline déterministe)
   - Tu perdrais 3x plus de temps que de bien le faire

2. **Déléguer la logique métier (synthesizer, drift, verdicts)**
   - C'est ta propriété intellectuelle
   - C'est ce qui fait la valeur du framework
   - Aucun SDK ne l'aura jamais par design

3. **Négliger la transparence des coûts**
   - Le problème n'est pas la marge des providers, c'est l'opacité des outils
   - Sans reçu détaillé, tu ne comprendras jamais pourquoi ça coûte cher
   - C'est un principe architectural, pas un accessoire

---

## 10. Ressources et Références

### 10.1 Documentation des outils

| Outil | Documentation |
|-------|---------------|
| Typer | https://typer.tiangolo.com/ |
| Mirascope | https://mirascope.dev/ |
| LangGraph | https://langchain-ai.github.io/langgraph/ |
| Pydantic v2 | https://docs.pydantic.dev/ |
| structlog | https://www.structlog.org/ |
| pytest | https://docs.pytest.org/ |
| pipx | https://pypa.github.io/pipx/ |

### 10.2 Tarifs des providers (Juillet 2026)

| Provider | Modèle | Input (par 1M tokens) | Output (par 1M tokens) |
|----------|--------|-----------------------|------------------------|
| Anthropic | Haiku | $0.25 | $1.25 |
| Anthropic | Sonnet | $3.00 | $15.00 |
| Anthropic | Opus | $15.00 | $75.00 |
| OpenAI | GPT-4o-mini | $0.15 | $0.60 |
| OpenAI | GPT-4o | $2.50 | $10.00 |
| Google | Gemini Flash | $0.075 | $0.30 |
| Google | Gemini Pro | $1.25 | $5.00 |

**Note :** Ces tarifs évoluent rapidement. Vérifie toujours les tarifs actuels sur les sites officiels.

### 10.3 Framework G.O.A.L. Cascade

| Document | Lien |
|----------|------|
| Framework de base | `framework-multi-agents.md` |
| Guide multi-cascade | `goal-cascade-multi-cascade.md` |
| Licence | MIT |
| Auteur | Eddie |
| Date | Juillet 2026 |

---

## 11. Prochaines Étapes

### 11.1 Décision immédiate

**Tu as maintenant toutes les informations pour démarrer.** La question n'est plus "comment faire" mais "quand commencer".

**Options :**
1. **Démarrer cette semaine** (recommandé) : tu as le plan, les outils, le temps estimé
2. **Attendre d'avoir plus de temps** : risque de procrastination, le plan deviendra obsolète
3. **Déléguer à un dev** : tu peux donner ce document à un dev senior, il aura toutes les infos

### 11.2 Action concrète pour cette semaine

**Si tu démarres maintenant :**

1. Crée le projet Python :
   ```bash
   mkdir goal-cli && cd goal-cli
   uv init
   uv add typer mirascope langgraph pydantic structlog
   ```

2. Crée la structure de dossiers :
   ```
   goal-cli/
   ├── src/
   │   └── goal/
   │       ├── cli.py          # Typer CLI
   │       ├── orchestrator.py # Logique G.O.A.L.
   │       ├── synthesizer.py  # Synthèse orientée objectif
   │       ├── providers.py    # Multi-provider Mirascope
   │       └── state.py        # LangGraph state machine
   ├── prompts/                # Templates Jinja
   ├── tests/
   └── pyproject.toml
   ```

3. Implémente la Semaine 1 (15-20 heures)

### 11.3 Support et communauté

**Si tu bloques :**
- Documentation des outils (liens en 10.1)
- GitHub Issues des libs (Mirascope, LangGraph)
- Stack Overflow (tag python, langgraph, etc.)
- Discord/Slack des communautés (LangChain, Anthropic, OpenAI)

**Si tu veux contribuer au framework G.O.A.L. :**
- Le framework est open source (licence MIT)
- Les contributions sont bienvenues (voir Section 13 du framework de base)
- Contact : Eddie (voir documents sources)

---

## Conclusion

**Ce plan chirurgical te donne tout ce dont tu as besoin pour construire le CLI G.O.A.L. Cascade :**

✅ **Architecture cible** claire (3 couches, ce que tu possèdes vs délègues)  
✅ **Outils justifiés** (pourquoi Python, pourquoi Mirascope/LangGraph, alternatives rejetées)  
✅ **Plan d'exécution** détaillé (6 semaines, livrables par semaine, temps estimé)  
✅ **Garde-fous** (transparence coûts, kill switch budgétaire, détection dérive)  
✅ **Anti-patterns** documentés (ce qu'il ne faut PAS faire)  
✅ **Checklists** actionnables (pré-démarrage, par semaine, post-production)  

**La décision est maintenant entre tes mains.** Tu as le plan, les outils, le temps estimé. La seule question restante est : quand commences-tu ?

---

<p align="center">
<strong>G.O.A.L. Cascade CLI — Plan Chirurgical</strong><br>
<em>De l'architecture à l'implémentation, sans détour.</em><br><br>
Chaque décision est justifiée. Chaque semaine a un livrable. Chaque garde-fou est actionnable.<br>
Le framework est prêt. Le CLI attend.
</p>

---

**Instructions pour sauvegarder cet artefact :**

1. Copie tout le contenu ci-dessus (depuis "# G.O.A.L. Cascade CLI" jusqu'à la fin)
2. Crée un nouveau fichier nommé `goal-cascade-cli-plan-chirurgical.md`
3. Colle le contenu
4. Sauvegarde

Tu as maintenant ton plan chirurgical complet, prêt à être utilisé comme référence pour l'implémentation.