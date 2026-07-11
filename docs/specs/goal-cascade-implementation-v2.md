# G.O.A.L. Cascade — Plan d'implémentation v2
## *Architecture technique définitive du CLI multi-cascade*

> **Document d'ingénierie v2.** Fusionne la profondeur technique (schemas, pseudo-code) et la rigueur opérationnelle (transparence coûts, kill switch) + corrige les angles morts que les deux versions précédentes oubliaient.

---

| | |
|---|---|
| **Version** | 2.0 (fusion technique + opérationnelle) |
| **Date** | Juillet 2026 |
| **Statut** | Spec technique définitive — prêt pour implémentation |
| **Licence** | MIT |
| **Auteur** | Eddie |
| **Sources** | `framework-multi-agents.md`, `goal-cascade-multi-cascade.md`, `reference-qwen-plan-chirurgical.md` |
| **Durée estimée** | 6 semaines (1 dev senior) ou 10 semaines (1 dev junior) |

---

## TL;DR

> **L'approche.** Construire un **CLI maison** (`goal-cascade-cli`) avec un **SDK d'orchestration** en fondation. On possède l'intelligence (synthesizer, state, verdicts), on délègue la plomberie (API providers, retries, streaming).
>
> **La transparence radicale.** Chaque run produit un **reçu détaillé** : tokens, coûts, taux de cache. Avec un **kill switch budgétaire** pour éviter les factures surprises.
>
> **La nouveauté v2.** Cette version corrige 5 angles morts que ni la v1 ni le plan chirurgical n'avaient traités : rate limits, tests qualité synthèse, intégration CI/CD, modularité prompts, versioning des runs.

---

## Table des matières

1. [Décision d'architecture — CLI maison vs fork](#1-décision-darchitecture--cli-maison-vs-fork)
2. [Stack technique et justifications](#2-stack-technique-et-justifications)
3. [Architecture en 3 couches](#3-architecture-en-3-couches)
4. [Schemas Pydantic — le typage du framework](#4-schemas-pydantic--le-typage-du-framework)
5. [Le synthesizer — cœur du framework](#5-le-synthesizer--cœur-du-framework)
6. [State machine et verdict STOP / CONTINUE](#6-state-machine-et-verdict-stop--continue)
7. [Multi-cascade graph executor](#7-multi-cascade-graph-executor)
8. [Cache exact + cache sémantique](#8-cache-exact--cache-sémantique)
9. [Transparence radicale des coûts 🆕](#9-transparence-radicale-des-coûts-)
10. [Rate limits et résilience 🆕](#10-rate-limits-et-résilience-)
11. [Intégration CI/CD (vérification déterministe) 🆕](#11-intégration-cicd-vérification-déterministe-)
12. [Modularité des prompts 🆕](#12-modularité-des-prompts-)
13. [Versioning et debugging des runs 🆕](#13-versioning-et-debugging-des-runs-)
14. [Onboarding & modes (libre / encadré) 🆕](#14-onboarding--modes-libre--encadré-)
15. [Structure du projet](#15-structure-du-projet)
16. [Plan de build en 6 semaines](#16-plan-de-build-en-6-semaines)
17. [CLI commands et UX](#17-cli-commands-et-ux)
18. [Risques et mitigations](#18-risques-et-mitigations)
19. [Anti-patterns à éviter](#19-anti-patterns-à-éviter)
20. [Checklists de production](#20-checklists-de-production)
21. [Tarifs des providers et benchmarks](#21-tarifs-des-providers-et-benchmarks)
22. [À traiter au moment du build](#22-à-traiter-au-moment-du-build)

---

## 1. Décision d'architecture — CLI maison vs fork

### 1.1 Le constat fondamental

G.O.A.L. Cascade et les CLIs existants (kimi-code, aider, opencode, claude-code) ne sont **pas le même type de logiciel**.

| Aspect | CLIs existants (chat augmenté) | G.O.A.L. Cascade (pipeline) |
|---|---|---|
| **Paradigme** | Conversationnel, linéaire | **Graph acyclique déterministe** |
| **Flux** | L'utilisateur discute, l'IA propose | La cascade exécute, l'arbitre décide |
| **État** | Context window du LLM | **State machine externe** (SQLite) |
| **Entre étapes** | Historique brut passé au modèle | **Synthèse orientée objectif** (couche filtrante) |
| **Modèles** | 1 modèle + fallbacks | **4 tiers stricts multi-providers**, rôles non interchangeables |
| **Arrêt** | L'utilisateur tape `/exit` | **Critère mathématique** Q(T), STOP par défaut |
| **Caching** | KV-cache implicite | **Exact dedans / sémantique dehors** (logique inverse) |
| **Coûts** | Opacité totale | **Transparence radicale** + kill switch |

### 1.2 Pourquoi forker serait un piège

Forker kimi-code (ou aider, ou claude-code) reviendrait à :

1. Comprendre leur architecture interne (leurs abstractions ne nous aident pas)
2. Tordre leur state management pour y faire entrer 4 itérations déterministes
3. Lutter contre leurs partis-pris UX ("l'assistant propose, tu valides") qui **contredisent** la vision ("la cascade exécute, l'arbitre décide")
4. Hériter de leurs bugs, leur roadmap, leurs dépendances — sans contrôle

> **On paierait la dette d'autrui + notre propre dette.**

### 1.3 La décision

> **Construire un CLI maison** avec un **SDK d'orchestration** en fondation. On possède la logique métier (synthèse, verdict, Q(T), frozen spec), on délègue la plomberie (API providers, retries, streaming) à des libs éprouvées.

### 1.4 Les 3 couches de valeur

| Couche | Ce qu'on construit (propriété intellectuelle) | Ce qu'on délègue (plomberie) |
|---|---|---|
| **Logique métier** | Synthesizer orienté objectif, drift detection, verdicts STOP/CONTINUE, frozen spec validator, Q(T) tracker | — |
| **Orchestration** | Graphe d'états G.O.A.L., branching conditionnel, checkpointing | LangGraph (state machine + SQLite natif) |
| **Multi-provider** | Règle de diversité stricte, cache exact activé, rotation des providers | Mirascope (API unifiée) |

> **Règle absolue :** Si on délègue la logique métier (synthesizer, drift, verdicts), on perd la valeur du framework. Cette couche doit être 100% maison.

---

## 2. Stack technique et justifications

### 2.1 Choix du langage : Python 3.11+

| Critère | Python ✅ | Go |
|---|---|---|
| Mirascope / LangGraph | 🟢 Natifs | ❌ Incompatible |
| Pydantic (typing strict) | 🟢 Natif, mature | 🟡 Moins idiomatique |
| Écosystème ML/IA | 🟢 Richesse inégalée | 🟡 Plus limité |
| POC en 6 semaines | 🟢 Réaliste | 🔴 10+ semaines |

**Décision : Python.** La valeur du framework est dans la logique métier, pas dans la performance du CLI. Python est le choix rationnel.

### 2.2 Dépendances — tableau de décision complet

| Dépendance | Rôle | Justification | Alternative rejetée | Raison du rejet |
|---|---|---|---|---|
| **Typer** | CLI framework | Simple, type-safe, auto-help | Click | Plus verbeux, moins moderne |
| **Mirascope** | Multi-provider | API unifiée Anthropic/OpenAI/Google, pydantic-first | LiteLLM | Moins type-safe, API moins propre |
| **LangGraph** | State machine | Branching STOP/CONTINUE natif + checkpointing SQLite | State machine maison | 3+ semaines de dev pour refaire |
| **Pydantic v2** | Validation | Typage strict des artefacts immuables, sérialisation | dataclasses | Pas de validation runtime |
| **SQLite** | Persistance | Checkpoints + cache sémantique, zéro config | PostgreSQL | Overkill pour un CLI local |
| **structlog** | Logging | Logs structurés, debuggable | logging standard | Pas de structure |
| **TOML** | Config | Standard Python moderne, lisible | YAML | Moins strict, parsing ambigu |
| **Jinja2** | Templates | Prompts customisables sans toucher au code | Strings hardcodées | Pas de personnalisation |
| **networkx** | Graphe topologique | Multi-cascade (phase 6) | Maison | Recoder ce qui existe |
| **numpy** | Similarité cosinus | Calcul vectoriel performant | Pur Python | Lent, moins clair |
| **rich** | Affichage terminal | Sorties lisibles, couleurs, tables | print | Illisible pour un CLI sérieux |
| **pytest** | Tests | Standard, async natif | unittest | Plus verbeux |
| **pipx** | Distribution | Installation globale isolée | pip install | Pollution environnement |

### 2.3 Ce qu'on n'utilise PAS (et pourquoi)

| Outil tentant | Pourquoi on le rejette |
|---|---|
| **LangChain** | Overhead, abstractions inutiles pour notre cas |
| **Redis** | Overkill pour un CLI local, SQLite suffit |
| **Docker** | Pas nécessaire pour un CLI Python installable |
| **FastAPI** | On n'a pas besoin d'un serveur, juste un CLI |
| **OpenTelemetry** | Overkill pour un projet solo/petite équipe |
| **Cache sémantique intra-cascade** | Tue la diversité multi-provider (Pilier 1) |

### 2.4 Versions minimales

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "mirascope>=1.0",
    "langgraph>=0.2",
    "pydantic>=2.0",
    "typer>=0.12",
    "jinja2>=3.1",
    "structlog>=24.0",
    "rich>=13.0",
    "networkx>=3.0",
    "numpy>=1.26",
]
```

---

## 3. Architecture en 3 couches

```
┌──────────────────────────────────────────────────────────────────┐
│                    COUCHE 1 — CLI (Typer)                         │
│                                                                   │
│  goal run <objective> --variant A --providers anthropic,openai   │
│  goal cascade plan <spec.md>                                      │
│  goal resume <run_id>                                             │
│  goal status <run_id>                                             │
│                                                                   │
│  Rôle : parsing args, affichage (rich), entry point               │
└────────────────────────────┬──────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│              COUCHE 2 — ORCHESTRATEUR G.O.A.L.                    │
│              (100% maison — c'est la valeur)                       │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐        │
│  │ Synthesizer  │  │ State Manager│  │ Verdict Engine   │        │
│  │ (filtre +    │  │ (SQLite,     │  │ (STOP/CONTINUE,  │        │
│  │  cosinus)    │  │  artefacts)  │  │  Q(T), limite 5) │        │
│  └──────────────┘  └──────────────┘  └──────────────────┘        │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐        │
│  │ Frozen Spec  │  │ Multi-Cascade│  │ Budget Tracker   │  🆕    │
│  │ Validator    │  │ Graph Exec.  │  │ (kill switch)    │        │
│  └──────────────┘  └──────────────┘  └──────────────────┘        │
│                                                                   │
│  ┌──────────────────────────────────────────────────────┐        │
│  │  CI/CD Integration Hook  🆕                           │        │
│  │  (linter, compilateur, tests — vérif déterministe)    │        │
│  └──────────────────────────────────────────────────────┘        │
└────────────────────────────┬──────────────────────────────────────┘
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│           COUCHE 3 — MULTI-PROVIDER (Mirascope)                   │
│                                                                   │
│  Anthropic (Claude)  ↔  OpenAI (GPT)  ↔  Google (Gemini)         │
│  + Qwen / DeepSeek (extensible)                                   │
│                                                                   │
│  + Rate Limit Handler  🆕   + Cache exact activé                  │
│  + Cost Tracker      🆕   + Retry / backoff exponentiel           │
└───────────────────────────────────────────────────────────────────┘
```

### 3.1 Principe de séparation

| Couche | Possède | Ne fait pas |
|---|---|---|
| **CLI** | Parsing, affichage, entry point | Logique métier, appels API |
| **Orchestrateur** | Synthèse, state, verdicts, budget | Appels API directs, affichage |
| **Provider** | Appels API, retries, cache exact | Logique de cascade |

> **Les dépendances vont vers le bas.** Le CLI dépend de l'orchestrateur qui dépend du provider. **Jamais l'inverse.**

---

## 4. Schemas Pydantic — le typage du framework

Le typage strict est ce qui distingue ce CLI d'un enchaînement de prompts. Chaque concept du framework devient un modèle Pydantic validé.

### 4.1 La synthèse orientée objectif

```python
from pydantic import BaseModel, Field
from typing import Literal

class GoalOrientedSynthesis(BaseModel):
    """Synthèse transmise entre les itérations (section 4 du framework)."""
    objective: str = Field(..., description="Objectif initial, reformulé en une phrase")
    key_decisions: list[str] = Field(
        ..., min_length=1, max_length=5,
        description="3 à 5 décisions clés maximum"
    )
    uncertainties: list[str] = Field(
        default_factory=list,
        description="Points non tranchés ou à vérifier"
    )
    next_instruction: str = Field(
        ..., description="Rôle de l'itération suivante + ce qu'elle doit produire"
    )
    iteration_from: int
    iteration_to: int
```

### 4.2 L'artefact exécutoire (charge utile immuable)

```python
class ImmutableArtifact(BaseModel):
    """Charge utile immuable transmise intacte entre les jonctions.
    Ne JAMAIS être synthétisée — la forme EST le signal."""
    artifact_type: Literal["code", "json_schema", "formula", "test", "config", "sql"]
    language: str | None = None  # ex: "python", "typescript"
    content: str = Field(..., description="Le contenu brut, non modifié")
    checksum: str = Field(..., description="Hash pour détecter toute altération")
    source_iteration: int
```

### 4.3 La frozen spec

```python
class Invariant(BaseModel):
    """Un invariant vérifiable de la frozen spec."""
    description: str
    category: Literal["functional", "structural", "non_negotiable"]
    verified: bool | None = None  # None = non encore vérifié

class FrozenSpec(BaseModel):
    """Spécification gelée d'un module. Aucun invariant ne peut
    être supprimé sans validation humaine."""
    module_name: str
    objective: str
    invariants: list[Invariant] = Field(..., min_length=1)
    max_lines: int = Field(default=3000, ge=100, le=10000)

    def all_verified(self) -> bool:
        return all(inv.verified for inv in self.invariants)

    def missing_invariants(self) -> list[Invariant]:
        return [inv for inv in self.invariants if not inv.verified]
```

### 4.4 Le contrat d'interface

```python
class InterfaceInvariant(BaseModel):
    description: str
    respected: bool | None = None

class InterfaceContract(BaseModel):
    """Contrat entre deux modules. Créé AVANT les cascades."""
    contract_id: str
    producer_module: str
    consumer_module: str
    output_description: str
    input_description: str
    exchange_format: str  # ex: "JSON Schema", "TypeScript types"
    invariants: list[InterfaceInvariant]
    error_cases: list[str] = Field(default_factory=list)
```

### 4.5 Le verdict de l'arbitre

```python
class Verdict(BaseModel):
    """Verdict de l'itération 4 (Arbitre)."""
    decision: Literal["STOP", "CONTINUE"]
    justification: str
    frozen_spec_check: list[Invariant]
    interface_checks: list[InterfaceInvariant] = []

    def is_valid(self) -> bool:
        """Un verdict CONTINUE doit avoir au moins un invariant manquant."""
        if self.decision == "CONTINUE":
            return any(not inv.verified for inv in self.frozen_spec_check)
        return True
```

### 4.6 Le reçu de coût 🆕

```python
class LLMCallRecord(BaseModel):
    """Enregistrement d'un appel LLM pour la transparence des coûts."""
    provider: str
    model: str
    iteration: int
    role: str  # producer, critic, adversary, arbiter
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float
    latency_ms: int
    timestamp: str

class RunReceipt(BaseModel):
    """Reçu détaillé d'un run complet."""
    run_id: str
    objective: str
    total_iterations: int
    final_verdict: str
    total_duration_s: float
    calls: list[LLMCallRecord]
    total_cost_usd: float
    cache_hit_rate: float  # cache_read_tokens / total_input_tokens
    projected_monthly_cost: float  # basé sur 10 runs/jour

    def summary_table(self) -> str:
        """Génère un tableau rich pour l'affichage CLI."""
        ...
```

### 4.7 L'état d'une cascade

```python
class IterationRole(str, Enum):
    PRODUCER = "producer"
    CRITIC = "critic"
    ADVERSARY = "adversary"
    ARBITER = "arbiter"

class CascadeState(BaseModel):
    """État persistant d'une cascade en cours d'exécution."""
    run_id: str
    objective: str
    variant: Literal["A", "B"]  # A=rédactionnel, B=technique
    current_iteration: int = 0
    max_iterations: int = Field(default=5, le=5)
    history: list[LLMCallRecord] = Field(default_factory=list)
    last_synthesis: GoalOrientedSynthesis | None = None
    artifacts: list[ImmutableArtifact] = Field(default_factory=list)
    frozen_spec: FrozenSpec | None = None
    interface_contracts: list[InterfaceContract] = Field(default_factory=list)
    final_verdict: Verdict | None = None
    status: Literal["running", "stopped", "forced_stop", "budget_exceeded"] = "running"
    accumulated_cost: float = 0.0
    parent_version: str | None = None  # 🆕 pour le versioning
```

---

## 5. Le synthesizer — cœur du framework

Le synthesizer est la pièce la plus originale du CLI. Il n'existe dans aucun autre outil.

### 5.1 Responsabilités

```
   Sortie brute         ┌──────────────────────┐        Entrée de
   de l'itération N  ──▶│     SYNTHESIZER      │──▶    l'itération N+1
                        │                      │
                        │  1. Sépare texte /   │        ┌─────────────┐
                        │     artefacts        │        │ Synthèse    │
                        │                      │        │ orientée    │
                        │  2. Synthétise le    │        │ objectif    │
                        │     texte (4 blocs)  │        │ (4 blocs)   │
                        │                      │        └─────────────┘
                        │  3. Préserve les     │        ┌─────────────┐
                        │     artefacts intacts│        │ Charge      │
                        │                      │        │ utile       │
                        │  4. Mesure la        │        │ immuable    │
                        │     similarité       │        │ (intacte)   │
                        │     cosinus(N, N-1)  │        └─────────────┘
                        │                      │
                        │  5. Détecte la dérive│
                        └──────────────────────┘
```

### 5.2 L'algorithme principal

```python
class Synthesizer:
    def __init__(self, provider, embedding_model, prompt_loader):
        self.provider = provider
        self.embedding_model = embedding_model
        self.prompt_loader = prompt_loader  # 🆕 Jinja2 loader (section 12)
        self.previous_embedding: np.ndarray | None = None

    def process(
        self,
        raw_output: str,
        objective: str,
        iteration_from: int,
        iteration_to: int,
        previous_artifacts: list[ImmutableArtifact] = []
    ) -> SynthesisResult:

        # 1. Extraire les artefacts immuables (code, JSON, formules)
        artifacts = self._extract_artifacts(raw_output, iteration_from)
        all_artifacts = self._merge_artifacts(previous_artifacts, artifacts)

        # 2. Synthétiser la partie narrative (via LLM, prompt chargé depuis template)
        synthesis = self._generate_synthesis(
            raw_output, objective, iteration_from, iteration_to
        )

        # 3. Calculer la similarité cosinus (détection de dérive)
        similarity = self._compute_cosine_similarity(raw_output)
        drift_status = self._evaluate_drift(similarity)

        return SynthesisResult(
            synthesis=synthesis,
            artifacts=all_artifacts,
            similarity_score=similarity,
            drift_status=drift_status
        )
```

### 5.3 La détection de dérive par similarité cosinus

```python
    def _compute_cosine_similarity(self, text: str) -> float | None:
        """Compare la sortie actuelle à la précédente.
        Similarité ≥ 0.95 = dérive (ancrage ou convergence)."""
        embedding = self.embedding_model.embed(text)

        if self.previous_embedding is None:
            self.previous_embedding = embedding
            return None  # Pas de comparaison possible à la première itération

        similarity = np.dot(embedding, self.previous_embedding) / (
            np.linalg.norm(embedding) * np.linalg.norm(self.previous_embedding)
        )
        self.previous_embedding = embedding
        return float(similarity)

    def _evaluate_drift(self, similarity: float | None) -> DriftStatus:
        if similarity is None:
            return DriftStatus.NO_DATA
        if similarity >= 0.95:
            return DriftStatus.CRITICAL  # STOP anticipé
        elif similarity >= 0.85:
            return DriftStatus.WARNING
        elif similarity >= 0.70:
            return DriftStatus.NORMAL
        else:
            return DriftStatus.DIVERGENT  # Attendu pour l'adversaire
```

> **🆕 Règle d'embedding unifié :** utiliser **un seul modèle d'embedding** (OpenAI `text-embedding-3`) pour tous les calculs de similarité, **indépendamment** du provider de la cascade. Évite les incohérences entre providers.

### 5.4 L'extraction des artefacts

```python
    def _extract_artifacts(self, text: str, iteration: int) -> list[ImmutableArtifact]:
        """Identifie les blocs de code, JSON, formules dans la sortie.
        Les sépare du texte narratif pour les préserver intacts."""
        artifacts = []

        # Détecter les blocs ```code...```
        for match in CODE_BLOCK_RE.finditer(text):
            artifacts.append(ImmutableArtifact(
                artifact_type="code",
                language=match.group("lang") or None,
                content=match.group("code"),
                checksum=hashlib.sha256(match.group("code").encode()).hexdigest()[:16],
                source_iteration=iteration
            ))

        # Détecter les blocs JSON
        for match in JSON_BLOCK_RE.finditer(text):
            artifacts.append(ImmutableArtifact(
                artifact_type="json_schema",
                content=match.group("json"),
                checksum=hashlib.sha256(match.group("json").encode()).hexdigest()[:16],
                source_iteration=iteration
            ))

        return artifacts
```

---

## 6. State machine et verdict STOP / CONTINUE

### 6.1 Le graphe d'états d'une cascade

```
                    ┌─────────────────┐
                    │   INIT          │
                    │   (objectif +   │
                    │    frozen spec) │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
              ┌────▶│  ITÉRATION N    │◀─────┐
              │     │  (rôle défini)  │      │
              │     └────────┬────────┘      │
              │              │               │
              │              ▼               │
              │     ┌─────────────────┐      │
              │     │  SYNTHESIZER    │      │
              │     │  + dérive check │      │
              │     └────────┬────────┘      │
              │              │               │
              │     ┌────────▼────────┐      │
              │     │  🆕 BUDGET OK ? │      │
              │     └───┬─────────┬────┘      │
              │         │OUI     │NON         │
              │         │        ▼            │
              │         │  ┌──────────┐       │
              │         │  │BUDGET_EXC│       │
              │         │  └──────────┘       │
              │         ▼                     │
              │     ┌─────────────────┐      │
              │     │  DÉRIVE ≥ 0.95? │      │
              │     └───┬─────────┬────┘      │
              │         │OUI     │NON         │
              │         ▼        │            │
              │  ┌──────────┐    │            │
              │  │FORCED STOP│   │            │
              │  └──────────┘    │            │
              │                  ▼            │
              │     ┌─────────────────┐      │
              │     │  N == 4 ?       │      │
              │     │  (Arbitre)      │      │
              │     └───┬─────────┬────┘      │
              │         │OUI     │NON         │
              │         ▼        │            │
              │  ┌──────────┐    │            │
              │  │ VERDICT  │    │            │
              │  │ STOP ?   │    │            │
              │  └──┬───┬───┘    │            │
              │  STOP│   │CONTINUE             │
              │     ▼   └────────┼────────────┘
              │ ┌──────┐         │ (reboucle, max 5)
              │ │ FIN  │         ▼
              │ └──────┘  ┌──────────────┐
              └───────────│ N < 5 ?      │
                          └──┬───────┬───┘
                          OUI│       │NON
                             ▼       ▼
                        (reboucle) FORCED STOP
```

### 6.2 L'exécuteur de cascade

```python
class CascadeExecutor:
    def __init__(self, synthesizer, state_manager, budget_tracker,
                 cicd_hook=None):  # 🆕
        self.synthesizer = synthesizer
        self.state_manager = state_manager
        self.budget_tracker = budget_tracker
        self.cicd_hook = cicd_hook  # 🆕 section 11

    def run(self, state: CascadeState) -> CascadeState:
        while state.status == "running":
            # 🆕 Check budget AVANT chaque itération
            if self.budget_tracker.is_exceeded(state.run_id):
                state.status = "budget_exceeded"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification=f"Budget dépassé: ${state.accumulated_cost:.2f}"
                )
                break

            # Limite absolue : 5 itérations
            if state.current_iteration >= state.max_iterations:
                state.status = "forced_stop"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification="Limite absolue de 5 itérations atteinte"
                )
                break

            # Exécuter l'itération suivante
            state.current_iteration += 1
            role = self._role_for_iteration(state.current_iteration)
            call_record, raw_output = self._execute_iteration(state, role)
            state.history.append(call_record)
            state.accumulated_cost += call_record.cost_usd

            # Passer par le synthesizer
            result = self.synthesizer.process(
                raw_output=raw_output,
                objective=state.objective,
                iteration_from=state.current_iteration,
                iteration_to=state.current_iteration + 1,
                previous_artifacts=state.artifacts
            )
            state.artifacts = result.artifacts

            # Détection de dérive
            if result.drift_status == DriftStatus.CRITICAL:
                state.status = "forced_stop"
                state.final_verdict = Verdict(
                    decision="STOP",
                    justification=f"Dérive détectée (sim={result.similarity_score:.3f})"
                )
                break

            # Itération 4 = Arbitre
            if role == IterationRole.ARBITER:
                verdict = self._parse_verdict(raw_output, state)
                if not verdict.is_valid():
                    raise InvalidVerdictError(verdict)
                state.final_verdict = verdict
                if verdict.decision == "STOP":
                    state.status = "stopped"

            # Sauvegarder (checkpointing)
            self.state_manager.save(state)

        return state
```

---

## 7. Multi-cascade graph executor

### 7.1 Le graphe topologique

```python
import networkx as nx

class ModuleGraph:
    """Graphe des modules et leurs dépendances."""
    def __init__(self):
        self.graph = nx.DiGraph()

    def add_module(self, module_id: str, spec: FrozenSpec):
        self.graph.add_node(module_id, spec=spec)

    def add_dependency(self, producer: str, consumer: str, contract: InterfaceContract):
        self.graph.add_edge(producer, consumer, contract=contract)

    def topological_order(self) -> list[str]:
        """Ordre de production : feuilles → intégration."""
        return list(nx.topological_sort(self.graph))

    def parallel_batches(self) -> list[list[str]]:
        """Modules indépendants = parallélisables."""
        return list(nx.layers(self.graph))
```

### 7.2 L'exécuteur multi-cascade

```python
class MultiCascadeExecutor:
    def __init__(self, module_graph: ModuleGraph,
                 cascade_executor: CascadeExecutor,
                 interface_checker: InterfaceChecker):  # 🆕 hybride
        self.graph = module_graph
        self.executor = cascade_executor
        self.checker = interface_checker

    def run_all(self) -> dict[str, CascadeState]:
        """Exécute toutes les cascades dans l'ordre topologique."""
        results = {}

        for batch in self.graph.parallel_batches():
            batch_results = {}
            for module_id in batch:
                contracts = self._get_contracts(module_id)
                state = CascadeState(
                    run_id=f"{module_id}-{uuid4()}",
                    objective=self.graph.graph.nodes[module_id]["spec"].objective,
                    variant="B",
                    frozen_spec=self.graph.graph.nodes[module_id]["spec"],
                    interface_contracts=contracts
                )
                batch_results[module_id] = self.executor.run(state)

            results.update(batch_results)

            # Tous les modules doivent STOP avant de continuer
            for module_id, state in batch_results.items():
                if state.status != "stopped":
                    raise ModuleFailedError(module_id, state)

        return results

    def run_integration(self, module_results: dict) -> CascadeState:
        """Cascade d'intégration finale (Phase 5)."""
        # 🆕 Vérification hybride : déterministe (CI/CD) d'abord
        integration_state = CascadeState(
            run_id=f"integration-{uuid4()}",
            objective="Assembler et valider le système complet",
            variant="B",
        )
        return self.executor.run(integration_state)
```

---

## 8. Cache exact + cache sémantique

### 8.1 Cache exact — activé par défaut

Le cache exact optimise les **préfixes stables** (objectif + frozen spec + contrats).

```python
PROVIDER_CACHE_CONFIG = {
    "anthropic": {"cache_control": {"type": "ephemeral"}},  # explicite, -90% coût
    "openai": {"auto": True},                                # automatique >1024 tokens
    "google": {"implicit": True},                            # implicite
}
```

### 8.2 Cache sémantique — détection de dérive UNIQUEMENT

```python
class DriftDetector:
    """Utilise les embeddings pour mesurer la similarité.
    Ne JAMAIS servir de réponse cachée à l'intérieur d'une cascade."""

    SIMILARITY_THRESHOLDS = {
        "critical": 0.95,   # STOP anticipé
        "warning": 0.85,    # Alerte
        "normal": 0.70,     # Progression normale
    }
```

> **Règle absolue** : le cache sémantique est en **lecture seule** pour la cascade. Il calcule la distance, il ne retourne jamais de résultat. *Exact dedans, sémantique dehors.*

---

## 9. Transparence radicale des coûts 🆕

> *Principe architectural venant du plan chirurgical de Qwen. Le CLI doit traiter la transparence des coûts comme un principe au même titre que la synthèse orientée objectif.*

### 9.1 Chaque run produit un reçu

**Chaque appel LLM capture** : `input_tokens`, `output_tokens`, `cache_read_tokens`, `cost_usd`, `latency_ms`.

**À la fin du run, le CLI affiche** :

```
╭───────────────────────────────────────────────────────────╮
│  📊 RUN RECEIPT — #a3f2c1                                   │
├───────────────────────────────────────────────────────────┤
│  Itérations : 4/5    Verdict : 🟢 STOP                     │
│  Durée : 3m 42s      Coût total : $0.087                   │
├───────────────────────────────────────────────────────────┤
│  ÉTAPE          PROVIDER    IN      OUT     CACHE   COÛT   │
│  ─────────────────────────────────────────────────────────  │
│  1 Producteur   Haiku       420     1850    0       $0.003 │
│  2 Critique     Sonnet      380     920     420     $0.004 │
│  3 Adversaire   Opus        510     1100    380     $0.024 │
│  4 Arbitre      Gemini-2M   680     850     510     $0.001 │
│  Synthèses (3)  Haiku       240     720     0       $0.001 │
│  ─────────────────────────────────────────────────────────  │
│  TOTAL                      2230    5440    1310    $0.033 │
│                                                             │
│  💰 Cache hit rate : 37%  (économie : ~$0.05)              │
│  📈 Projeté (10 runs/jour) : ~$10/mois                     │
╰───────────────────────────────────────────────────────────╯
```

### 9.2 Le kill switch budgétaire

```toml
# ~/.goal/config.toml
[budget]
max_per_run = 0.50      # un run ne peut pas dépasser $0.50
max_per_day = 10.00     # plafond journalier
warn_at_percent = 80    # alerte à 80% du budget
hard_stop = true        # stopper net, pas juste avertir
```

```python
class BudgetExceeded(Exception):
    """Levé quand le budget est atteint. Le run est interrompu proprement,
    l'état est sauvegardé (checkpoint), l'utilisateur peut reprendre
    après ajustement du budget."""
```

### 9.3 Comment G.O.A.L. réduit mécaniquement les coûts

| Levier | Mécanisme | Économie |
|---|---|---|
| Synthèse orientée objectif | Input N+1 ≈ 300 tokens, pas 5000 | **-80% inputs** |
| Cache exact sur préfixe stable | Objectif + Frozen Spec ≈ 1200 tokens identiques | **-90% préfixe** |
| Charge utile immuable | Code transmis en bloc, pas re-tokenisé | **-30% tokens code** |
| STOP par défaut | Pas de boucle infinie | **Élimine les runs à 3x** |
| Cascade ascendante | Iter 1 = petit modèle ($0.001/1K) | **-70% itération 1** |

> **Coût réel d'un run G.O.A.L. optimisé : ~$0.08** vs ~$0.75 pour un run naïf. **Soit 10x moins cher.**

---

## 10. Rate limits et résilience 🆕

> *Angle mort oublié par les deux versions précédentes. 4 itérations × 3+ providers = beaucoup d'appels. Sans gestion des rate limits, le CLI casse en production.*

### 10.1 Le rate limit handler

```python
class RateLimitHandler:
    """Gère les retries avec backoff exponentiel et fallback provider."""
    
    MAX_RETRIES = 3
    INITIAL_BACKOFF_S = 1.0
    BACKOFF_MULTIPLIER = 2.0
    
    # Providers de fallback par tier
    FALLBACK_CHAIN = {
        "anthropic": ["openai", "google"],
        "openai": ["anthropic", "google"],
        "google": ["anthropic", "openai"],
    }

    async def call_with_retry(
        self, provider: str, prompt: str, tier: str
    ) -> LLMResponse:
        for attempt in range(self.MAX_RETRIES):
            try:
                return await self.providers[provider].call(prompt, tier)
            except RateLimitError:
                if attempt < self.MAX_RETRIES - 1:
                    wait = self.INITIAL_BACKOFF_s * (self.BACKOFF_MULTIPLIER ** attempt)
                    logger.warning(
                        f"Rate limit {provider}, retry in {wait}s",
                        attempt=attempt + 1, provider=provider
                    )
                    await asyncio.sleep(wait)
                else:
                    # Fallback vers un autre provider du même tier
                    fallback = self._get_fallback(provider)
                    logger.warning(f"Fallback {provider} → {fallback}")
                    return await self.providers[fallback].call(prompt, tier)
```

### 10.2 Les stratégies de résilience

| Problème | Stratégie |
|---|---|
| Rate limit (429) | Backoff exponentiel (1s, 2s, 4s) puis fallback provider |
| Timeout provider | Retry (2x) puis fallback |
| Provider indisponible | Fallback automatique vers provider équivalent du même tier |
| Quota dépassé | Notification + kill switch (ne pas continuer à échouer) |
| Erreur parsing JSON LLM | Retry avec prompt "corrige ton JSON" (max 2x) |

> **Important** : le fallback doit respecter la **règle de diversité** — on bascule vers un provider *différent*, pas une instance du même. Sinon la valeur du Pilier 1 s'effondre.

---

## 11. Intégration CI/CD (vérification déterministe) 🆕

> *Angle mort partagé. Qwen mentionnait "Hard Gate" sans spécifier comment câbler un linter/compilateur. Voici l'intégration concrète.*

### 11.1 Le hook CI/CD

```python
class CICDHook:
    """Exécute des vérifications déterministes pendant la cascade
    d'intégration. Pour le formel (types, schémas), un outil déterministe
    est supérieur à un LLM."""

    CHECKERS = {
        "typescript": ["tsc --noEmit"],
        "python_types": ["mypy", "pyright"],
        "json_schema": ["ajv validate"],  
        "python_schema": ["pydantic"],  # validation native
        "sql": ["sqlite3 --validate"],
        "tests": ["pytest", "jest"],
    }

    def run_deterministic_checks(
        self, contract: InterfaceContract, artifacts: list[ImmutableArtifact]
    ) -> DeterministicCheckResult:
        """Vérifie ce qui peut l'être de manière 100% déterministe.
        Retourne avant l'appel LLM — si ça échoue, pas besoin de LLM."""
        
        failures = []
        for artifact in artifacts:
            checker_cmd = self.CHECKERS.get(artifact.artifact_type)
            if checker_cmd:
                result = subprocess.run(
                    checker_cmd, input=artifact.content,
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    failures.append(
                        CheckFailure(
                            artifact=artifact,
                            checker=checker_cmd,
                            error=result.stderr
                        )
                    )
        return DeterministicCheckResult(
            passed=len(failures) == 0,
            failures=failures,
            method="deterministic"
        )
```

### 11.2 La vérification hybride (rappel)

L'itération 2 de la cascade d'intégration applique les deux temps :

```python
class InterfaceChecker:
    def __init__(self, cicd_hook: CICDHook):
        self.cicd = cicd_hook

    def check(self, contract, modules) -> CheckResult:
        # 1. Déterministe d'abord (CI/CD hors LLM)
        det_result = self.cicd.run_deterministic_checks(contract, modules.artifacts)
        if not det_result.passed:
            return CheckResult(
                passed=False, failures=det_result.failures,
                method="deterministic"
            )

        # 2. LLM ensuite (pour le sémantique : intention, cohérence doc)
        sem_result = self._run_llm_checks(contract, modules)
        return CheckResult(
            passed=sem_result.passed, failures=sem_result.failures,
            method="hybrid"
        )
```

| Type de vérification | Outil | Quand |
|---|---|---|
| Types, schémas, tests | **Déterministe** (CI/CD) | Toujours en premier |
| Sémantique, intention | **LLM** (itération 2) | Seulement si le déterministe passe |

---

## 12. Modularité des prompts 🆕

> *Angle mort oublié par les deux versions. Pour l'open source, un utilisateur doit pouvoir personnaliser ses prompts sans toucher au code.*

### 12.1 Le système de templates hiérarchique

```python
class PromptLoader:
    """Charge les prompts depuis une hiérarchie de répertoires.
    L'utilisateur peut surcharger n'importe quel prompt sans toucher au code."""
    
    SEARCH_PATHS = [
        "./.goal/prompts/",           # 🆕 surcharge locale projet (priorité max)
        "~/.goal/prompts/",           # 🆕 surcharge utilisateur
        "<package>/prompts/",         # prompts par défaut du package
    ]

    def load(self, prompt_name: str, **context) -> str:
        """Charge un template Jinja2 et le rend avec le contexte."""
        for path in self.SEARCH_PATHS:
            template_file = Path(path) / f"{prompt_name}.j2"
            if template_file.exists():
                env = Environment(loader=FileSystemLoader(template_file.parent))
                template = env.get_template(template_file.name)
                return template.render(**context)
        raise PromptNotFoundError(prompt_name)
```

### 12.2 La surcharge utilisateur

Un utilisateur peut créer `~/.goal/prompts/iteration_3.j2` pour **remplacer** le prompt de l'adversaire sans modifier le package. Le CLI charge en priorité :
1. `./.goal/prompts/` (projet)
2. `~/.goal/prompts/` (utilisateur)
3. `<package>/prompts/` (défaut)

### 12.3 Variables disponibles dans les templates

```jinja2
# Exemple: iteration_3.j2 (Adversaire)
Tu es un contradicteur professionnel.

OBJECTIF À GARDER EN TÊTE :
{{ objective }}

TRAVAIL ACTUEL :
{{ synthesis.summary }}

FROZEN SPEC :
{{ frozen_spec.to_markdown() }}

{% if artifacts %}
ARTEFACTS À EXAMINER :
{% for artifact in artifacts %}
```{{ artifact.language or "" }}
{{ artifact.content }}
```
{% endfor %}
{% endif %}
```

---

## 13. Versioning et debugging des runs 🆕

> *Angle mort oublié par les deux versions. Sans versioning, impossible de comparer deux runs ou de déboguer pourquoi un run a divergé.*

### 13.1 Le schema de versioning

```python
class RunVersion(BaseModel):
    """Version d'un run, pour comparaison et debugging."""
    run_id: str
    parent_run_id: str | None = None  # si c'est un retry/variation
    version_label: str  # ex: "v1-original", "v2-prompt-modifié"
    created_at: str
    config_hash: str  # hash de la config utilisée (providers, variants, prompts)
    prompt_hashes: dict[str, str]  # hash de chaque prompt utilisé
    status: str
    total_cost: float
```

### 13.2 Les commandes de debugging

```bash
# Lister toutes les versions d'un run
goal versions <run_id>

# Comparer deux runs (où ont-ils divergé ?)
goal diff <run_id_1> <run_id_2>

# Rejouer un run avec une modification
goal replay <run_id> --modify-prompt iteration_3 --branch v2

# Inspector l'état à une itération donnée
goal inspect <run_id> --iteration 3
```

### 13.3 Le diff de runs

```
$ goal diff a3f2c1 b8e4d2

╭─────────────────────────────────────────────────────╮
│  DIFF : a3f2c1 vs b8e4d2                             │
├─────────────────────────────────────────────────────┤
│                                                      │
│  CONFIG :                                            │
│    Providers : identiques ✓                          │
│    Prompt iter 3 : DIFFÉRENT ⚠️                      │
│      (a3f2c1: "Trouve les angles morts")             │
│      (b8e4d2: "Trouve les failles, sois impitoyable")│
│                                                      │
│  EXÉCUTION :                                         │
│    Itération 1-2 : identiques (cache hit)            │
│    Itération 3 : DIVERGENCE ici                      │
│      a3f2c1 : 4 angles morts, sim=0.68               │
│      b8e4d2 : 7 angles morts, sim=0.61 (plus agressif)│
│    Itération 4 : verdict différent                   │
│      a3f2c1 : STOP                                   │
│      b8e4d2 : CONTINUE (manque couverture)            │
│                                                      │
│  COÛT : a3f2c1 $0.08 | b8e4d2 $0.12 (+50%)           │
╰─────────────────────────────────────────────────────╯
```

---

## 14. Onboarding & modes (libre / encadré) 🆕

> *Avant de lancer une cascade, le CLI propose une phase de démarrage. Ce choix structure tout le reste. Inspiré de la **requirements elicitation** (génie logiciel) et de la méthode **BMAD** (AI-driven dev).*

### 14.1 Pourquoi une phase de démarrage

Lancer une cascade G.O.A.L. sans avoir clarifié l'objectif, l'audience et les contraintes revient à **construire sans fondations**. La cascade produira quelque chose, mais probablement à côté de la cible.

Notre propre conversation en a été la démonstration : nous n'avons pas écrit le framework immédiatement. Nous avons d'abord posé des questions (ton, longueur, langue, public, théorie), puis validé les intuitions scientifiquement, puis produit. **La phase de découverte a nourri la cascade.**

C'est un principe de dev senior : *"Mesurez deux fois, coupez une fois."*

#### Validation scientifique et industrielle

| Source | Apport |
|---|---|
| **Requirements Elicitation** (Karl Wiegers, [16 bonnes pratiques](https://medium.com/analysts-corner/16-good-practices-for-requirements-elicitation-9a805c663c84)) | Définir les business requirements, identifier les stakeholders et user classes avant de spécifier |
| **ACM Practitioners Study** ([dl.acm.org](https://dl.acm.org/doi/10.1145/3613372.3613410)) | Les techniques les plus efficaces : interviews, brainstorming, use cases, user stories |
| **BMAD Method** ([GitHub](https://github.com/EvolutionAPI/BMAD-METHOD-BY-EVOLUTION)) | 21 agents IA spécialisés (Analyst, PM, Architect, Dev, QA), 50+ workflows guidés — chaque projet commence par une découverte structurée |

> **La phase de découverte n'est pas optionnelle en génie logiciel sérieux.** C'est le facteur n°1 de succès/échec des projets.

### 14.2 Les deux modes de démarrage

Le CLI propose deux modes au `goal new`. **Les deux modes préservent intégralement la structure des 4 agents** de la cascade. La différence est uniquement dans la préparation en amont.

#### Mode 1 — Libre

| Aspect | Détail |
|---|---|
| **Quand** | L'utilisateur maîtrise sa méthode, sait exactement ce qu'il veut |
| **Comment** | Il enchaîne les prompts à sa guise, gère lui-même sa progression |
| **Structure des agents** | **Disponible mais non forcée** — l'utilisateur peut lancer une cascade quand il le décide |
| **Analogie** | Le dev senior qui ouvre un REPL et improvise |

```bash
$ goal new --mode free
╭─ Mode libre ─────────────────────────────────────╮
│ Vous gérez votre flux. Les commandes cascade     │
│ restent disponibles quand vous le décidez :      │
│   goal run --objective "..."                     │
│   goal cascade plan ...                          │
╰──────────────────────────────────────────────────╯
> _
```

#### Mode 2 — Encadré

| Aspect | Détail |
|---|---|
| **Quand** | Projet sérieux, MVP, ou utilisateur qui veut être guidé |
| **Comment** | Séquence de questions obligatoire avant de lancer la cascade |
| **Structure des agents** | **Forcée** — la phase de découverte débouche obligatoirement sur une cascade G.O.A.L. |
| **Analogie** | Le tech lead qui impose un kickoff structuré avant de coder |

```bash
$ goal new --mode guided
╭─ Mode encadré — Phase de découverte ─────────────╮
│ Répondez aux questions. Elles produiront le      │
│ ProjectBrief qui alimentera la cascade.           │
╰──────────────────────────────────────────────────╯

? Quel est l'objectif de ce livrable ? (une phrase)
> _

? Pour qui est-ce ? (audience cible)
> _
...
```

### 14.3 La séquence de découverte (mode encadré)

Inspirée de notre conversation et des pratiques d'élicitation. **7 questions** qui produisent le `ProjectBrief`.

| # | Question | Ce qu'elle capture | Alimente |
|---|---|---|---|
| **1** | *Quel est l'objectif de ce livrable ?* (une phrase) | L'objectif invariant | Itération 1 (prompt) + Itération 4 (alignement) |
| **2** | *Pour qui est-ce ?* (audience cible, niveau) | Le public | Itération 1 (`PUBLIC CIBLE`) |
| **3** | *Quelles contraintes ?* (format, longueur, langue, délai) | Les bornes | Itération 1 (`CONTRAINTES`) |
| **4** | *Quels sont les critères de succès ?* (qu'est-ce qui rend le livrable acceptable ?) | La définition de "fini" | Itération 4 (critères d'arrêt) |
| **5** | *MVP ou livrable complet ?* (portée) | Le scope (cascade unique vs multi-cascade) | Choix de l'exécuteur |
| **6** | *Quels risques connaissez-vous ?* (angles morts anticipés) | Les points faibles attendus | Itération 3 (point de départ de l'adversaire) |
| **7** | *Quelles sources/vérifications prioritaires ?* | Les faits à valider en premier | Itération 2 (priorité de vérification) |

> **Ces 7 questions ne sont pas un questionnaire passif.** Le Discovery Agent peut relancer, clarifier, challenger une réponse vague — comme un bon BA (Business Analyst). Si l'utilisateur répond *"pour tout le monde"*, l'agent relance : *"précisez : tout le monde technique, ou grand public ?"*

### 14.4 Le ProjectBrief — résultat de la découverte

```python
class ProjectBrief(BaseModel):
    """Résultat de la phase de découverte. Produit la fondation
    de la cascade. Sans ce brief, la cascade travaille à l'aveugle."""
    
    # Capturé par les 7 questions
    objective: str = Field(..., description="Objectif invariant, une phrase")
    audience: str = Field(..., description="Public cible + niveau")
    constraints: list[str] = Field(
        default_factory=list,
        description="Format, longueur, langue, délai"
    )
    success_criteria: list[str] = Field(
        ..., min_length=1,
        description="Ce qui rend le livrable acceptable"
    )
    scope: Literal["mvp", "full"] = "mvp"
    known_risks: list[str] = Field(
        default_factory=list,
        description="Angles morts anticipés"
    )
    priority_sources: list[str] = Field(
        default_factory=list,
        description="Faits à valider en priorité"
    )
    
    # Dérivé
    variant: Literal["A", "B"]  # A=rédactionnel, B=technique
    requires_multi_cascade: bool = False  # si scope=full et taille > 3000 lignes
    
    # Métadonnées
    created_at: str
    discovery_mode: Literal["free", "guided"]
```

### 14.5 Le Discovery Agent

L'agent qui mène la phase de découverte (mode encadré). Ce n'est **pas** un des 4 agents de la cascade — c'est un agent **pré-cascade**, avec un rôle de Business Analyst.

```python
class DiscoveryAgent:
    """Mène la phase de découverte en mode encadré.
    Pose les 7 questions, clarifie les réponses vagues,
    produit le ProjectBrief."""
    
    QUESTIONS = [
        DiscoveryQuestion(
            id="objective",
            question="Quel est l'objectif de ce livrable ? (une phrase)",
            clarifiers=["Précisez : est-ce un objectif mesurable ?",
                        "Une seule phrase, pas deux."]
        ),
        DiscoveryQuestion(
            id="audience",
            question="Pour qui est-ce ? (audience cible)",
            clarifiers=["Précisez le niveau : débutant, intermédiaire, expert ?",
                        "Évitez 'tout le monde' — soyez spécifique."]
        ),
        # ... 5 autres questions
    ]
    
    def run(self) -> ProjectBrief:
        answers = {}
        for q in self.QUESTIONS:
            answer = self._ask(q)
            # Clarifier si la réponse est trop vague
            while self._is_too_vague(answer):
                clarification = self._pick_clarifier(q)
                answer = self._ask_again(q, clarification, answer)
            answers[q.id] = answer
        
        return self._build_brief(answers)
```

### 14.6 Le mapping découverte → cascade

C'est le point critique : **la découverte nourrit la cascade, elle ne la remplace pas.** Chaque réponse devient une entrée précise d'une itération.

```
   PHASE DE DÉCOUVERTE                    CASCADE G.O.A.L.
   ─────────────────                      ─────────────────

   Q1 Objectif        ────────────────▶  Itération 1 (Producteur)
   Q2 Audience        ────────────────▶     prompt.objective
   Q3 Contraintes     ────────────────▶     prompt.public_cible
                                           prompt.constraints

   Q4 Critères succès  ────────────────▶  Itération 4 (Arbitre)
                                           critères d'arrêt

   Q5 MVP/complet     ────────────────▶  Choix de l'exécuteur
                                           (cascade unique vs multi)

   Q6 Risques connus   ────────────────▶  Itération 3 (Adversaire)
                                           point de départ de la critique

   Q7 Sources prior.   ────────────────▶  Itération 2 (Critique)
                                           priorité de vérification
```

> **Sans la découverte, les itérations tournent à vide. Avec elle, chaque agent a une cible précise.**

### 14.7 Le mode hybride

Un utilisateur en mode libre peut **basculer** vers le guidé à tout moment :

```bash
# En mode libre, l'utilisateur réalise qu'il a besoin de structure
> /guided

╭─ Bascule en mode encadré ─────────────────────────╮
│ Je vais vous poser 7 questions pour structurer   │
│ votre projet. Vous pourrez reprendre le mode     │
│ libre ensuite.                                   │
╰───────────────────────────────────────────────────╯
```

Et inversement, après un ProjectBrief généré en mode guidé, l'utilisateur peut **reprendre la main** et ajuster avant de lancer la cascade.

### 14.8 L'inspiration de notre conversation

Notre collaboration a suivi, sans le formaliser, exactement ce schéma :

| Notre étape | Équivalent G.O.A.L. |
|---|---|
| *"Créer un article LinkedIn sur le multi-agent"* | Q1 Objectif |
| Clarification : ton, longueur, langue | Q2-Q3 Audience + Contraintes |
| Recherche scientifique (ensemble learning, Q(T)…) | Découverte approfondie |
| *"Prouver scientifiquement"* | Q4 Critères de succès |
| Revue Qwen (adversaire) | Itération 3 |
| Production du framework (3 documents) | Cascade complète |
| Intégration des retours Qwen | Correction post-arbitre |

> **La phase de découverte est le carburant de la cascade.** C'est ce que vous avez identifié intuitivement, et c'est ce que la science du génie logiciel valide.

---

## 15. Structure du projet

```
goal-cascade-cli/
├── pyproject.toml
├── README.md
├── LICENSE                          # MIT
├── src/
│   └── goal_cascade/
│       ├── __init__.py
│       ├── cli.py                   # Entry point Typer (couche 1)
│       │
│       ├── schemas/                 # Couche 2 — typage Pydantic
│       │   ├── __init__.py
│       │   ├── synthesis.py         # GoalOrientedSynthesis, ImmutableArtifact
│       │   ├── frozen_spec.py       # FrozenSpec, Invariant
│       │   ├── interface.py         # InterfaceContract, InterfaceInvariant
│       │   ├── verdict.py           # Verdict
│       │   ├── receipt.py           # 🆕 LLMCallRecord, RunReceipt
│       │   ├── state.py             # CascadeState, IterationRole
│       │   └── versioning.py        # 🆕 RunVersion
│       │
│       ├── orchestrator/            # Couche 2 — logique métier
│       │   ├── __init__.py
│       │   ├── synthesizer.py       # Cœur : synthèse + artefacts + cosinus
│       │   ├── cascade_executor.py  # State machine, verdict, limite 5
│       │   ├── verdict_engine.py    # STOP/CONTINUE
│       │   ├── drift_detector.py    # Similarité cosinus, seuils
│       │   ├── frozen_validator.py  # Vérification invariants
│       │   ├── budget_tracker.py    # 🆕 Kill switch budgétaire
│       │   ├── prompt_loader.py     # 🆕 Templates hiérarchiques Jinja2
│       │   ├── cicd_hook.py         # 🆕 Vérification déterministe
│       │   └── state_manager.py     # Persistance SQLite
│       │
│       ├── discovery/               # 🆕 Phase d'onboarding (section 14)
│       │   ├── __init__.py
│       │   ├── agent.py             # DiscoveryAgent (pose les 7 questions)
│       │   ├── brief.py             # ProjectBrief (schema)
│       │   └── questions.py         # Les 7 questions + clarifiers
│       │
│       │   ├── cicd_hook.py         # 🆕 Vérification déterministe
│       │   ├── prompt_loader.py     # 🆕 Templates hiérarchiques Jinja2
│       │   └── state_manager.py     # Persistance SQLite
│       │
│       ├── multicascade/            # Couche 2 — multi-cascade
│       │   ├── __init__.py
│       │   ├── module_graph.py      # Graphe topologique (networkx)
│       │   ├── interface_checker.py # Vérification hybride
│       │   └── multi_executor.py    # Exécuteur parallèle + intégration
│       │
│       ├── providers/               # Couche 3 — abstraction provider
│       │   ├── __init__.py
│       │   ├── base.py              # Interface unifiée
│       │   ├── anthropic.py         # + cache_control
│       │   ├── openai.py            # + cache auto
│       │   ├── google.py            # + cache implicite
│       │   ├── rate_limiter.py      # 🆕 Backoff + fallback
│       │   └── cost_tracker.py      # 🆕 Calcul coûts par provider
│       │
│       └── prompts/                 # Templates Jinja2 (surchargeables)
│           ├── iteration_1.j2
│           ├── iteration_2.j2
│           ├── iteration_3.j2
│           ├── iteration_4.j2
│           ├── synthesis.j2
│           ├── frozen_spec_gen.j2
│           ├── interface_gen.j2
│           └── integration_4.j2
│
└── tests/
    ├── test_synthesizer.py
    ├── test_verdict_engine.py
    ├── test_frozen_validator.py
    ├── test_cascade_executor.py
    ├── test_drift_detector.py
    ├── test_budget_tracker.py       # 🆕
    ├── test_rate_limiter.py         # 🆕
    ├── test_cicd_hook.py            # 🆕
    ├── test_prompt_loader.py        # 🆕
    └── test_multi_executor.py
```

---

## 16. Plan de build en 6 semaines

> ⚠️ **Estimation réaliste.** 89-115 heures de travail effectif pour un dev senior.

### Vue d'ensemble

```
Semaine 1 → Fondations + single cascade minimale
Semaine 2 → Multi-provider + cache exact + 🆕 rate limits
Semaine 3 → Synthesizer + artefacts immuables + 🆕 tests qualité synthèse
Semaine 4 → LangGraph state machine + branching + 🆕 budget tracker
Semaine 5 → Détection de dérive + cache sémantique + 🆕 versioning
Semaine 6 → Multi-cascade + intégration + 🆕 CI/CD hook + 🆕 modularité prompts
```

### Détail par semaine

#### Semaine 1 — Fondations + single cascade (15-20h)
- Projet Python avec `uv`, structure modulaire
- CLI Typer : `goal init`, `goal run`, `goal status`
- 4 prompts en templates Jinja2
- Exécuteur linéaire : Itération 1→2→3→4
- State persisté en JSON (SQLite viendra en semaine 4)
- 1 provider (Anthropic)
- **Critère :** `goal run --objective "..."` produit un livrable après 4 itérations

#### Semaine 2 — Multi-provider + résilience (12-15h)
- Mirascope pour Anthropic + OpenAI + Google
- 🆕 Rate limit handler (backoff + fallback)
- Validation diversité providers (refus si même famille)
- Cache exact Anthropic activé (`cache_control`)
- Config TOML (`~/.goal/config.toml`)
- Logging structlog
- **Critère :** un run utilise 4 providers différents, config rejetée si non conforme

#### Semaine 3 — Synthesizer + artefacts (15-20h)
- Synthesizer pipeline + validation Pydantic (4 blocs, max 5 décisions)
- Charge utile immuable (`ImmutableArtifact`)
- Extraction code/JSON/formules
- 🆕 Tests de qualité synthèse (métrique : la synthèse préserve-t-elle la complexité ?)
- Mode `--no-synth` pour debug
- **Critère :** entre chaque itération, le prompt contient uniquement 4 blocs + artefacts

#### Semaine 4 — State machine + budget (15-20h)
- Graphe LangGraph : nœuds producer/synth/critic/adversary/arbiter
- Edge conditionnelle STOP/CONTINUE
- Compteur + STOP forcé à 5
- Checkpointing SQLite natif LangGraph
- `goal resume <run_id>` pour relancer un run interrompu
- 🆕 Budget tracker + kill switch
- 🆕 Reçu de coût détaillé
- **Critère :** `goal run` produit STOP à itération 4 ou rebouclage vers 5, jamais au-delà

#### Semaine 5 — Détection de dérive + versioning (12-15h)
- Embeddings pour chaque sortie (modèle unifié OpenAI)
- Similarité cosinus entre N et N+1
- Alertes selon seuils (≥0.95 = STOP anticipé)
- Dashboard ASCII dans `goal status`
- Cache sémantique inter-runs (SQLite + embeddings)
- 🆕 Versioning des runs (`goal versions`, `goal diff`)
- **Critère :** `goal status` affiche la "vitesse" de la cascade, un run stagnant est stoppé

#### Semaine 6 — Multi-cascade + intégration (20-25h)
- `goal cascade plan <spec.md>` → génère `plan.json`
- Exécuteur topologique (networkx)
- 🆕 Hook CI/CD (vérification déterministe : tsc, mypy, pytest)
- Vérification hybride (déterministe d'abord, LLM ensuite)
- `goal cascade run <plan.json>` → N cascades parallèles
- Cascade d'intégration (Phase 5)
- 🆕 Modularité prompts (surcharges `~/.goal/prompts/`)
- **Critère :** `goal cascade run` produit un livrable > 10 000 lignes avec qualité de 500 lignes

### Récapitulatif des temps

| Semaine | Heures | Cumul |
|---|---|---|
| 1 | 15-20 | 15-20 |
| 2 | 12-15 | 27-35 |
| 3 | 15-20 | 42-55 |
| 4 | 15-20 | 57-75 |
| 5 | 12-15 | 69-90 |
| 6 | 20-25 | 89-115 |
| **Total** | **89-115h** | — |

**En semaines :** ~6 sem (senior) / ~10 sem (junior) / ~9-12 sem (temps partiel 10h/sem)

---

## 17. CLI commands et UX

### 16.1 Commandes principales

```bash
# Cascade unique
goal run \
  --objective "Un article LinkedIn sur le multi-agent" \
  --variant A \
  --providers anthropic,openai,google

# Avec frozen spec
goal run \
  --objective "Refactorer le module auth" \
  --variant B \
  --frozen-spec ./auth.frozen.yaml

# Multi-cascade
goal cascade init mon-projet
goal cascade plan --objective "..." --max-modules 5
goal cascade run
goal cascade integrate

# Debugging 🆕
goal status <run_id>          # dashboard avec dérive + coûts
goal resume <run_id>          # reprendre un run interrompu
goal versions <run_id>        # lister les versions
goal diff <id1> <id2>         # comparer deux runs
goal inspect <run_id> -i 3    # voir l'état à l'itération 3
```

### 16.2 Affichage pendant un run (rich)

```
╭──────────────────────────────────────────────────────────╮
│  G.O.A.L. Cascade — Run #a3f2c1                            │
│  Objectif : Un article LinkedIn sur le multi-agent         │
│  Variant : A (rédactionnel)                                │
│  Providers : Anthropic → OpenAI → Google → Gemini          │
│  Budget : $0.087 / $0.50 (17%)                             │
╰──────────────────────────────────────────────────────────╯

  Itération 1/5 — Producteur (Haiku)               ✅  $0.003
  ├─ Synthèse générée (4 blocs)
  ├─ Similarité : N/A (première)
  └─ 3 artefacts extraits

  Itération 2/5 — Critique (Sonnet)                ✅  $0.004
  ├─ Synthèse générée
  ├─ Similarité : 0.72 (normal)
  └─ 2 hallucinations flaguées

  Itération 3/5 — Adversaire (Opus)                ✅  $0.024
  ├─ Synthèse générée
  ├─ Similarité : 0.68 (divergent — attendu)
  └─ 4 angles morts identifiés

  Itération 4/5 — Arbitre (Gemini 2M)              ✅  $0.001
  ├─ Frozen spec : 5/5 invariants présents
  ├─ Verdict : 🟢 STOP
  └─ "Livrable aligné à l'objectif"

  ─────────────────────────────────────────────────
  ✅ Cascade terminée en 4 itérations — $0.032
  📊 Reçu détaillé : goal status a3f2c1
  📄 Livrable sauvegardé : ./output/run-a3f2c1.md
```

---

## 18. Risques et mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| **LangGraph overhead** | Moyenne | Moyen | Commencer sans (state JSON en S1). Ajouter en S4. |
| **Coût API multi-provider** | Élevée | Élevé | Cache exact par défaut (−90%). Kill switch. Reçu détaillé. |
| **Embeddings incohérents** | Moyenne | Moyen | Un seul modèle d'embedding (OpenAI) pour tous les calculs. |
| **Rate limits provider** | Élevée | Moyen | 🆕 Backoff exponentiel + fallback provider équivalent. |
| **Timeline optimiste** | Élevée | Faible | S1 seule = 2 sem réalistes. Multi-cascade pas avant S6. |
| **Parsing artefacts fragile** | Moyenne | Moyen | Regex + validation Pydantic. Fallback manuel. |
| **Verdict CONTINUE en boucle** | Faible | Élevé | Limite absolue 5. `forced_stop` protège. |
| **Budget explose** | Faible | Élevé | 🆕 Kill switch hard stop à `max_per_run`. |
| **Fausse diversité providers** | Moyenne | Moyen | Validation au démarrage, refus si même famille. |

---

## 19. Anti-patterns à éviter

| Anti-pattern | Symptôme | Parade |
|---|---|---|
| **Abstraction prématurée** | Code complexe, dur à debug | YAGNI — construire seulement le nécessaire |
| **State machine maison** | 3+ semaines perdues | Utiliser LangGraph |
| **Cache sémantique intra-cascade** | Diversité tuée | Exact dedans, sémantique dehors |
| **Pas de tracking de coûts** | Budget explose | Reçu détaillé + kill switch |
| **Multi-cascade trop tôt** | Cascade simple cassée | Maîtriser la simple d'abord (S1-S5) |
| **Historique brut transmis** | Ancrage, context rot, Woozle | Synthèse orientée objectif obligatoire |
| **Fausse diversité providers** | Erreurs corrélées | Règle de diversité stricte (3+ providers) |
| **Forker un CLI existant** | Dette d'autrui + la nôtre | CLI maison + SDK |

### Les 3 erreurs fatales

1. **Forker un CLI existant** (aider, claude-code, kimi-code) — on paierait la dette d'autrui + la nôtre
2. **Déléguer la logique métier** (synthesizer, drift, verdicts) — c'est la propriété intellectuelle
3. **Négliger la transparence des coûts** — sans reçu, on ne comprend jamais pourquoi ça coûte cher

---

## 20. Checklists de production

### 19.1 Pré-démarrage

- [ ] Python 3.11+ installé
- [ ] `uv` installé
- [ ] Clés API : Anthropic, OpenAI, Google
- [ ] Git configuré
- [ ] Éditeur configuré
- [ ] Temps disponible : 6 semaines × 15h/sem minimum

### 19.2 Par semaine

**S1 :** projet créé, CLI Typer, 4 prompts Jinja, exécuteur linéaire, state JSON, 1 provider
**S2 :** Mirascope 3 providers, validation diversité, config TOML, cache Anthropic, structlog, 🆕 rate limiter
**S3 :** synthesizer, schema 4 blocs, ImmutableArtifact, validation auto, 🆕 tests qualité synthèse
**S4 :** graphe LangGraph, branching STOP/CONTINUE, STOP forcé 5, checkpointing SQLite, `goal resume`, 🆕 budget tracker, 🆕 reçu
**S5 :** embeddings, cosinus, alertes dérive, dashboard ASCII, cache sémantique inter-runs, 🆕 versioning
**S6 :** `goal cascade plan`, exécuteur topologique, 🆕 hook CI/CD, vérification hybride, `goal cascade run`, intégration, 🆕 modularité prompts

### 19.3 Post-production (avant release)

- [ ] Documentation README complète
- [ ] 3 cas d'usage testés et documentés
- [ ] Benchmarks coût/latence/qualité publiés
- [ ] Tests unitaires > 80% couverture
- [ ] Tests d'intégration passent
- [ ] Package sur PyPI
- [ ] Installation via `pipx` testée
- [ ] Licence MIT ajoutée
- [ ] CHANGELOG initialisé

---

## 21. Tarifs des providers et benchmarks

### 20.1 Tarifs indicatifs (Juillet 2026)

| Provider | Modèle | Input (par 1M tokens) | Output (par 1M tokens) |
|---|---|---|---|
| Anthropic | Haiku | $0.25 | $1.25 |
| Anthropic | Sonnet | $3.00 | $15.00 |
| Anthropic | Opus | $15.00 | $75.00 |
| OpenAI | GPT-4o-mini | $0.15 | $0.60 |
| OpenAI | GPT-4o | $2.50 | $10.00 |
| Google | Gemini Flash | $0.075 | $0.30 |
| Google | Gemini Pro | $1.25 | $5.00 |

> ⚠️ Ces tarifs évoluent vite. Vérifier toujours les sites officiels.

### 20.2 Benchmark coût G.O.A.L. vs naïf

| Config | Tokens totaux | Coût |
|---|---|---|
| Naïf (single model, historique brut, 5 iter) | ~50K | ~$0.75 |
| **G.O.A.L. optimisé** (synthèse + cache + cascade) | ~8K | **~$0.08** |

> **Un run G.O.A.L. coûte 10x moins cher qu'un run naïf.**

### 20.3 Livrables finaux

| Livrable | Description |
|---|---|
| `goal` (CLI) | Installable via `pipx install goal-cascade` |
| Documentation | README + guide d'usage + référence commandes |
| Templates Jinja | Tous les prompts, customisables sans toucher au code |
| Config d'exemple | `~/.goal/config.toml` |
| 3 cas d'usage | Article LinkedIn / fonction Python / mini-app multi-modules |
| Benchmarks | Coût, latence, qualité vs baseline single-model |
| Tests | Unitaires (synthesizer, drift, budget) + intégration |

---

## 22. À traiter au moment du build

> *Points identifiés en fin de conception. Pas de sur-ingénierie maintenant : ils seront traités au moment de coder.*

### 22.1 Orchestration cloisonnée du plan technique

Le plan de build (section 16) est aujourd'hui une liste séquentielle par semaine. Au moment de l'implémentation, le découper en **tâches cloisonnées interconnectées** (comme le multi-cascade du framework) :

- Un module = une tâche bornée (ex : synthesizer, budget tracker, rate limiter)
- Des dépendances explicites entre tâches (ex : cascade_executor dépend de synthesizer + budget)
- Le CLI doit être son propre premier client : appliquer G.O.A.L. multi-cascade à son propre build

### 22.2 Métriques de tokens par itération, persistées

Chaque itération doit produire un **fichier consultable** avec ses métriques complètes, pas juste un affichage terminal :

```
~/.goal/runs/<run_id>/
├── iteration_1.json   # tokens in/out/cache, coût, latence, sortie brute
├── iteration_2.json
├── iteration_3.json
├── iteration_4.json
├── receipt.json       # reçu agrégé
└── final_output.md    # livrable final
```

Pour audit, debug et comparaison de runs.

### 22.3 Métrique de qualité de la synthèse

Le synthesizer fait 5 choses, mais **on ne mesure pas s'il le fait bien**. Risque : la synthèse écrase une information critique et les itérations suivantes dérivent.

Ne pas réinventer la roue — utiliser les métriques NLP existantes :
- **ROUGE** (coverage : la synthèse couvre-t-elle les concepts clés ?)
- **BERTScore** (similarité sémantique entre brute et synthèse)
- **Coverage metric** : % de concepts clés de la sortie brute présents dans la synthèse

Objectif : une métrique objective *"cette synthèse préserve X% de la complexité de la sortie brute"*.

### 22.4 Roadmap v2 — Outil hybride CLI + SaaS

Pour plus tard. Le CLI reste open source. Un **dashboard web optionnel** (freemium) pourrait apporter :
- Visualisation des runs et de la dérive
- Benchmarking entre runs
- Diagnostic qualité de synthèse

**Avantage :** modèle économique clair. **Inconvénient :** complexité infrastructure. **Décision :** à traiter en v2, pas maintenant.

---

<p align="center">
  <strong>G.O.A.L. Cascade — Plan d'implémentation v2</strong><br>
  <em>L'intelligence est dans l'orchestration. La plomberie est déléguée. La transparence est radicale.</em><br><br>
  On possède le synthesizer, le state, les verdicts, le budget.<br>
  On délègue les API, les retries, le streaming.<br>
  On révèle chaque token, chaque coût, chaque dérive.<br>
  C'est la séparation qui rend le CLI défendable, maintenable et trustworthy.
</p>
