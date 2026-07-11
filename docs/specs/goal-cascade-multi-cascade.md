# G.O.A.L. Cascade — Guide multi-cascade
## *Production de livrables complexes par décomposition modulaire*

> **Companion du framework G.O.A.L. Cascade.** Ce document étend le framework de base aux **livrables de grande taille** (code, architectures, rapports) qui dépassent les capacités d'une cascade unique.

---

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | Juillet 2026 |
| **Statut** | Open source — prêt pour la production |
| **Licence** | MIT |
| **Auteur** | Eddie |
| **Pré-requis** | Lecture et compréhension de `framework-multi-agents.md` (le framework de base) |

---

## TL;DR

> **Le problème.** Sur un gros livrable, l'IA dérive : elle simplifie la complexité au fil des itérations (*dérive de simplification*) et sa qualité chute quand le code dépasse quelques milliers de lignes (*dégradation de longueur*). Une seule cascade G.O.A.L. ne suffit plus.
>
> **La méthode.** On découpe le livrable en **modules indépendants** (comme des forks de développeurs). Chaque module reçoit **sa propre cascade G.O.A.L. complète**, protégée par une **spécification gelée** (*frozen spec*) et bornée à **~3000 lignes**. Les modules s'assemblent via des **contrats d'interface**, puis une **cascade d'intégration** valide le tout.
>
> **Le résultat.** Un livrable de 10 000, 50 000 ou 100 000 lignes produit avec la même qualité qu'un livrable de 500 lignes — parce qu'aucune cascade ne traite plus que ce qu'elle maîtrise.

---

## Table des matières

1. [Le problème : pourquoi une cascade ne suffit plus](#1-le-problème--pourquoi-une-cascade-ne-suffit-plus)
2. [La solution : décomposition modulaire](#2-la-solution--décomposition-modulaire)
3. [Phase 1 — Planification modulaire](#3-phase-1--planification-modulaire)
4. [Phase 2 — Frozen spec (spécification gelée)](#4-phase-2--frozen-spec-spécification-gelée)
5. [Phase 3 — Contrat d'interface](#5-phase-3--contrat-dinterface)
6. [Phase 4 — Cascades parallèles](#6-phase-4--cascades-parallèles)
7. [Phase 5 — Cascade d'intégration](#7-phase-5--cascade-dintégration)
8. [Diagrammes & schémas](#8-diagrammes--schémas)
9. [Prompts prêts à copier](#9-prompts-prêts-à-copier)
10. [Checklists de production multi-cascade](#10-checklists-de-production-multi-cascade)
11. [Anti-patterns spécifiques au multi-cascade](#11-anti-patterns-spécifiques-au-multi-cascade)
12. [Annexes scientifiques](#12-annexes-scientifiques)

---

## 1. Le problème : pourquoi une cascade ne suffit plus

Le framework G.O.A.L. Cascade (document principal) fonctionne remarquablement sur un livrable de taille moyenne : un article, une fonction complexe, un composant, un rapport. Mais quand le livrable grossit — une application complète, une base de code entière, un document technique de plusieurs dizaines de pages — **deux phénomènes apparaissent qui dépassent les garde-fous du framework de base**.

### 1.1 La dérive de simplification

> *L'IA commence ambitieuse, puis rabote la complexité au fil des itérations, jusqu'à livrer une version appauvrie.*

**Le mécanisme.** Face à une tâche complexe, l'IA régresse vers la solution la plus "probable" dans ses données d'entraînement. Or les exemples de code simple sont **beaucoup plus fréquents** que les exemples de code complexe. C'est la **régression vers la moyenne** : le modèle remplace votre problème spécifique par un problème générique qu'il sait résoudre.

C'est amplifié par la **servilité** (*sycophancy*) : les LLMs sont entraînés (RLHF) pour plaire plutôt que pour avoir raison. Un papier récent ([arXiv 2508.02087](https://arxiv.org/html/2508.02087v4)) montre qu'une simple opinion suffit à déclencher un comportement servile.

**Le plus sournoix** : aucune étape ne trahit la dérive visiblement. Chaque simplification paraît *raisonnable* au moment où elle se fait. C'est l'accumulation qui détruit.

```
Itération 1 : [Tâche complexe, 100%]  → Code complet mais imparfait
Itération 2 : [Correction]            → Un cas limite est "simplifié" pour gagner du temps
Itération 3 : [Refactor]              → Une abstraction est aplatie ("trop compliqué" → viré)
Itération 4 : [Finalisation]          → Un edge case non traité reste non traité
                                        ────────────────────────────────
                                        Résultat : [Version appauvrie, 70%]
```

### 1.2 La dégradation par longueur

> *Plus l'IA génère de code, plus la qualité baisse.*

Plusieurs sources convergent vers la même conclusion :

- **"Brevity is the soul of wit"** (2024) : la qualité chute avec la longueur des fichiers.
- **"Can LLMs Generate Quality Code? A 40,000-Line Experiment"** ([HackerNoon](https://hackernoon.com/can-llms-generate-quality-code-a-40000-line-experiment)) : *"Comme les humains, les LLMs produisent du code bâclé avec le temps — juste plus vite."*
- **Reasoning degradation** : la qualité du raisonnement chute même avec de grandes fenêtres de contexte (effet *lost in the middle*).

**Le seuil empirique** : au-delà d'environ **3000 lignes** par module, l'IA devient "bâclée". En dessous, elle reste fiable.

### 1.3 Pourquoi le framework de base ne suffit pas

| Garde-fou du framework de base | Limite sur gros livrable |
|---|---|
| Synthèse orientée objectif | Filtre le bruit... mais peut *aussi* écraser la complexité légitime |
| Itération 3 (Adversaire) | Identifie les angles morts, mais ne mesure pas la perte de complexité |
| Limite de 5 itérations | Borné le temps, mais pas la taille du livrable |
| Arbitre d'alignement | Subjectif sur un gros livrable — où commence la "dérive" ? |

> **Conclusion** : pour les gros livrables, il faut un mécanisme supplémentaire qui **rend la perte de complexité détectable et bloquante**. C'est l'objet de ce guide.

---

## 2. La solution : décomposition modulaire

L'idée est empruntée à l'ingénierie logicielle classique : **aucun développeur ne code tout un projet seul**. On découpe en modules, chacun borné, puis on assemble.

### 2.1 La métaphore dev

| Équipe de dev | G.O.A.L. multi-cascade |
|---|---|
| Un dev = un module/fork | Une cascade = un module |
| Chaque dev a un scope borné | Chaque cascade a une **frozen spec** |
| Interfaces claires entre modules | **Contrats d'interface** entre cascades |
| Merge final → un tout | **Cascade d'intégration** → un livrable complet |
| Pas de dev qui code tout le projet | Pas de cascade qui traite tout le système |

### 2.2 Le principe unifiant

> **Chaque module est traité par sa propre cascade G.O.A.L. complète** (4 itérations + synthèse orientée objectif + limite de 5). La taille de chaque module reste sous le seuil de fiabilité (~3000 lignes). Les modules s'assemblent via des contrats d'interface, puis une cascade d'intégration valide le tout.

### 2.3 Validation scientifique

La décomposition modulaire est l'une des approches **les plus étudiées et les plus efficaces** pour améliorer les LLMs sur des tâches complexes :

- **DecompRL** ([arXiv](https://arxiv.org/html/2607.02390v1)) : *"Plutôt que d'échantillonner plus fort, nous rendons la tâche plus facile en décomposant les problèmes en modules plus petits, indépendamment résolvables."* Résultat : les modèles résolvent des problèmes **plus difficiles** avec la décomposition qu'en les attaquant d'un bloc.
- **FunCoder** ([OpenReview](https://openreview.net/forum?id=cFqAANINgW)) : stratégie divide-and-conquer qui décompose récursivement une tâche complexe en sous-tâches.
- **Self-consistency** ([arXiv 2203.11171](https://arxiv.org/abs/2203.11171)) : échantillonnage de plusieurs chemins de raisonnement et sélection du plus consistent — valide le pattern MapReduce.
- **Apple "Divide or Conquer"** ([GitHub](https://github.com/apple/ml-divide-or-conquer)) : la phase de décomposition peut être distillée et généralise bien.

### 2.4 Les 5 phases

```
PHASE 1          PHASE 2          PHASE 3
Planification → Frozen spec  →  Contrat d'interface
(découpage)      (par module)     (entre modules)
   │                 │                  │
   └─────────────────┴──────────────────┘
                      │
                      ▼
                 PHASE 4
             Cascades parallèles
        (un module = une G.O.A.L.)
                      │
                      ▼
                 PHASE 5
          Cascade d'intégration
          (assemblage + validation)
                      │
                      ▼
               ✅ LIVRABLE COMPLET
```

Les sections suivantes détaillent chaque phase.

---

## 3. Phase 1 — Planification modulaire

> **Objectif** : découper le livrable complet en modules indépendants, chacun sous le seuil de fiabilité (~3000 lignes).

### 3.1 Principes de découpage

Un bon découpage respecte ces principes :

1. **Indépendance** — chaque module doit pouvoir être développé sans connaître le détail interne des autres.
2. **Cohérence interne** — un module ne mélange pas des responsabilités non liées (principe de responsabilité unique).
3. **Taille bornée** — chaque module reste sous ~3000 lignes (seuil de fiabilité LLM).
4. **Frontières claires** — chaque frontière entre modules est définissable en une interface.
5. **Découplage réel** — ⚠️ le code doit être *réellement* découplable. Sur un monolithe legacy fortement couplé (état global omniprésent, dépendances implicites), les frontières n'existent pas et le LLM va halluciner des découpages propres. Voir [limite de périmètre legacy](#) dans le framework de base (section 1.4). Dans ce cas, le problème est humain d'abord (refonte architecturale), pas IA.

### 3.2 Critères de découpage

| Type de livrable | Critère de découpage naturel |
|---|---|
| **Application logicielle** | Par couche (UI, logique, données) ou par feature (auth, paiement, profil) |
| **API / backend** | Par endpoint ou par domaine fonctionnel |
| **Documentation technique** | Par chapitre ou par composant |
| **Rapport analytique** | Par section (contexte, méthode, résultats, conclusion) |
| **Système d'agents IA** | Par agent (un module = un agent + son prompt system) |

### 3.3 La règle de taille

> **~3000 lignes par module maximum.** Si un module dépasse, on le sous-découpe.

Ce seuil est empirique et défendable par la dégradation de qualité documentée au-delà. Il inclut le code ET les tests ET la documentation du module. Quand un module approche les 3000 lignes, c'est un signal qu'il regroupe en réalité **deux** modules.

### 3.4 Output de la phase 1

La phase 1 produit un **plan de découpage** :

```text
PLAN DE DÉCOUPAGE — [Nom du livrable]
══════════════════════════════════════════════════════
Objectif global : [une phrase]

MODULES :
  M1 : [nom] — [responsabilité] — ~[X] lignes estimées
  M2 : [nom] — [responsabilité] — ~[X] lignes
  M3 : [nom] — [responsabilité] — ~[X] lignes
  ...

DÉPENDANCES :
  M2 dépend de M1 (interface : ...)
  M3 dépend de M1 et M2 (interface : ...)

ORDRE DE PRODUCTION :
  M1 → M2 → M3 (séquentiel car dépendances)
  OU
  M1, M2, M3 en parallèle (si indépendants)
══════════════════════════════════════════════════════
```

---

## 4. Phase 2 — Frozen spec (spécification gelée)

> **Objectif** : empêcher la dérive de simplification à l'intérieur d'un module.

### 4.1 Principe

Avant de lancer la cascade d'un module, on fige une **spécification contractuelle** : la liste de tous les éléments de complexité **obligatoires**. À chaque itération, le module doit passer un contrôle de conformité — **zéro perte tolérée**.

### 4.2 Pourquoi c'est chirurgical

| Sans frozen spec | Avec frozen spec |
|---|---|
| La complexité s'érode en silence | Chaque perte devient un **défaut bloquant explicite** |
| L'arbitre juge subjectivement | L'arbitre coche des invariants **booléens** (présent/absent) |
| La dérive est invisible | La dérive devient **détectable et quantifiable** |
| La servilité gagne | Le contrat **désarme** la servilité |

### 4.3 Template de frozen spec

```text
FROZEN SPEC — Module [M1 : nom]
══════════════════════════════════════════════════════
Contrat de complexité. Aucun élément ci-dessous ne peut
être supprimé, simplifié ou contourné sans validation
humaine explicite. Chaque invariant est vérifiable.

INVARIANTS FONCTIONNELS (présence obligatoire) :
  ☐ [Ex: gestion des erreurs réseau avec retry exponentiel]
  ☐ [Ex: validation des entrées selon le schéma X]
  ☐ [Ex: compatibilité ascendante avec l'API v2]
  ☐ [Ex: tests unitaires sur les 5 cas limites listés]

INVARIANTS STRUCTURELS :
  ☐ [Ex: séparation présentation / logique / données]
  ☐ [Ex: aucun import circulaire]
  ☐ [Ex: toutes les fonctions publiques sont typées]

NON-NÉGOCIABLES :
  ☐ [Ex: aucune dépendance ajoutée sans justification]
  ☐ [Ex: aucune edge case marquée "TODO" en final]

TAILLE MAX : ~3000 lignes (code + tests + doc module)
══════════════════════════════════════════════════════
```

### 4.4 Intégration dans la cascade

La frozen spec s'intègre à **deux moments** de la cascade G.O.A.L. du module :

1. **À la création (avant itération 1)** — elle devient une entrée de l'itération 1, au même titre que l'objectif.
2. **Au contrôle (itération 4, Arbitre)** — l'arbitre doit passer en revue chaque invariant et répondre PRÉSENT/ABSENT. Tout invariant manquant = verdict CONTINUE obligatoire.

---

## 5. Phase 3 — Contrat d'interface

> **Objectif** : garantir que les modules s'assemblent, malgré leur indépendance.

### 5.1 Le problème de l'assemblage

Si chaque module est développé indépendamment, comment garantir qu'ils se pluguent ? C'est le problème classique de l'intégration. En dev, on le résout par les **interfaces** (API, types, signatures). Pour les LLMs, le piège est : **l'IA peut halluciner une interface** qui ne correspond pas à ce que le module adjacent attend.

### 5.2 La solution : le contrat d'interface

Entre chaque frontière de modules, on définit un **contrat d'interface** qui sert de relais. C'est l'équivalent d'une signature de fonction ou d'une API :

```text
CONTRAT D'INTERFACE — Module M1 → Module M2
══════════════════════════════════════════════════════
M1 produit (output) : [description précise]
M2 consomme (input) : [description précise]
Format d'échange : [JSON schema / types / structure]

Invariants d'interface :
  ☐ M1 DOIT produire un objet avec les champs : ...
  ☐ M2 DOIT gérer les cas : ...
  ☐ Toute déviation = défaut bloquant
══════════════════════════════════════════════════════
```

### 5.3 Types de frontières

| Type de frontière | Exemple de contrat |
|---|---|
| **Code → Code** | Signature de fonction, types TypeScript, schéma JSON |
| **Code → Données** | Format de fichier, schéma de DB, contraintes de validation |
| **Agent → Agent** | Format de message (input/output), états possibles |
| **Section → Section** | (Documentation) Glossaire partagé, concepts introduits, transitions |
| **Module → Système** | Configuration, variables d'environnement, dépendances externes |

### 5.4 Règle de cohérence

> **Le contrat d'interface est créé AVANT les cascades des modules qu'il relie.** Il est partagé par les deux modules comme frozen spec additionnelle.

Chaque module reçoit donc, en entrée de sa cascade :
- Sa **frozen spec** (complexité interne obligatoire)
- Le ou les **contrats d'interface** qui le relient aux modules adjacents

---

## 6. Phase 4 — Cascades parallèles

> **Objectif** : produire chaque module avec sa propre cascade G.O.A.L. complète.

### 6.1 Principe

Chaque module suit **exactement** le framework G.O.A.L. Cascade de base (voir `framework-multi-agents.md`) :

- 4 itérations (Producteur → Critique → Adversaire → Arbitre)
- Synthèse orientée objectif à chaque jonction
- Limite de 5 itérations par module
- Cascade multi-provider (petit → très grand modèle)

**L'ajout** : chaque cascade reçoit en entrée supplémentaire :
- La **frozen spec** du module (contrôle de complexité)
- Les **contrats d'interface** avec les modules adjacents (contrôle d'assemblage)

### 6.2 Parallèle vs séquentiel

| Configuration | Quand l'utiliser |
|---|---|
| **Parallèle** | Modules indépendants (aucune dépendance entre eux). Les cascades peuvent tourner en même temps. |
| **Séquentiel** | Modules en dépendance (M2 a besoin du résultat de M1). On attend que M1 soit validé avant de lancer M2. |
| **Hybride** | Graphe de dépendances partiel. On identifie les chaînes critiques et les branches indépendantes. |

### 6.3 Ordre recommandé

Même en parallèle, il est souvent préférable de **produire d'abord les modules "feuilles"** (sans dépendance descendante) puis de remonter vers les modules qui assemblent. C'est l'ordre topologique du graphe de dépendances.

```
     M1 (feuille)     M2 (feuille)
          │                │
          ▼                ▼
        M3 (dépend de M1, M2)
                │
                ▼
        M4 (dépend de M3)
```

### 6.4 Le livrable de chaque cascade

À la fin de sa cascade, chaque module produit :

1. ✅ **Le code/contenu du module** (validé par l'arbitre)
2. ✅ **Le rapport de conformité** à la frozen spec (tous les invariants cochés)
3. ✅ **Le rapport de conformité** aux contrats d'interface
4. ✅ **Le verdict STOP** de l'arbitre

Tant qu'un module n'a pas ces 4 éléments, il n'est pas "plugable".

---

## 7. Phase 5 — Cascade d'intégration

> **Objectif** : assembler les modules et valider le tout.

### 7.1 Pourquoi une cascade supplémentaire

Même si chaque module est validé individuellement, **l'assemblage peut révéler des incohérences** : une interface mal comprise, un contrat non respecté, une interaction inattendue entre modules. La cascade d'intégration est une **G.O.A.L. Cascade complète** appliquée à l'assemblage.

### 7.2 Les 4 itérations de la cascade d'intégration

| # | Rôle | Mission |
|---|---|---|
| **1** | **Assembleur** | Pluguer les modules selon les contrats d'interface. Produire le système assemblé. |
| **2** | **Vérificateur d'interfaces** | Vérifier que chaque contrat d'interface est respecté. Flaguer les déviations. |
| **3** | **Adversaire système** | Tester les cas limites de l'intégration : que se passe-t-il si M1 envoie une donnée inattendue à M2 ? |
| **4** | **Arbitre global** | Valider l'alignement avec l'objectif global (Phase 1). Vérifier toutes les frozen specs. STOP ou CONTINUE. |

#### Précision importante — vérification hybride (déterministe + LLM)

> ⚠️ **Identifié par revue externe adversariale.** L'itération 2 ne doit pas tout vérifier au LLM.

La vérification d'interface se fait en **deux temps complémentaires** :

1. **Déterministe d'abord (CI/CD, hors cascade)** — pour les contrats formels
   - Types TypeScript → `tsc`
   - JSON Schema → Ajv, Pydantic
   - Schémas de DB → migrations SQL, validateurs
   - Tests d'intégration → suite de tests automatisée

2. **LLM ensuite (itération 2)** — pour ce que le déterministe **ne peut pas** vérifier
   - **Sémantique** : "ce champ doit représenter un âge valide, pas un timestamp"
   - **Intention** : "ce module doit gérer les retries, pas juste les exposer"
   - **Cohérence** : alignment entre la doc d'interface et l'implémentation réelle

| Type de contrat | Outil |
|---|---|
| Types TypeScript, JSON Schema, SQL | ✅ **Déterministe** (CI/CD) |
| Sémantique, intention, cohérence doc/code | ✅ **LLM** (itération 2) |

> **Règle** : ne jamais déléguer au LLM une vérification qu'un compilateur ou un linter peut faire à 100% de précision. Le LLM est pour l'irréductible sémantique.

### 7.3 Le critère d'arrêt de l'intégration

La cascade d'intégration a un critère d'arrêt plus strict que les cascades de module :

> **Tous les contrats d'interface doivent être validés.** Si un seul contrat est non respecté, le verdict est CONTINUE — il faut retourner à la cascade du module responsable, corriger, puis recommencer l'intégration.

### 7.4 Limite absolue d'intégration

La cascade d'intégration suit la même règle de 5 itérations max. Si après 5 cycles d'intégration le système ne tient pas, c'est un signal que **le découpage initial (Phase 1) était mauvais** — les frontières entre modules sont mal placées. Il faut alors revenir à la Phase 1 et redécouper.

---

## 8. Diagrammes & schémas

### 8.1 Architecture multi-cascade complète

```
┌──────────────────────────────────────────────────────────────────┐
│                    LIVRABLE COMPLET (le "tout")                    │
│                                                                   │
│   Phase 1 : planification modulaire (découpage en N modules)       │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                ┌────────────┼────────────┐
                ▼            ▼            ▼
         ┌──────────┐  ┌──────────┐  ┌──────────┐
         │ MODULE 1 │  │ MODULE 2 │  │ MODULE 3 │
         └────┬─────┘  └────┬─────┘  └────┬─────┘
              │             │             │
   Phase 2 → │  Frozen spec (par module)  │
   Phase 3 → │  Contrat d'interface       │
              │             │             │
              ▼             ▼             ▼
        ╔═══════════╗ ╔═══════════╗ ╔═══════════╗
        ║ CASCADE   ║ ║ CASCADE   ║ ║ CASCADE   ║
        ║ G.O.A.L.  ║ ║ G.O.A.L.  ║ ║ G.O.A.L.  ║
        ║           ║ ║           ║ ║           ║
        ║ 4 itér.   ║ ║ 4 itér.   ║ ║ 4 itér.   ║
        ║ frozen    ║ ║ frozen    ║ ║ frozen    ║
        ║ spec ✓    ║ ║ spec ✓    ║ ║ spec ✓    ║
        ║ ~3000 ln  ║ ║ ~3000 ln  ║ ║ ~3000 ln  ║
        ╚═════╤═════╝ ╚═════╤═════╝ ╚═════╤═════╝
              │             │             │
              ▼             ▼             ▼
        [Module 1]   [Module 2]   [Module 3]
              │             │             │
              └─────────────┼─────────────┘
                            │
                            ▼
              ┌──────────────────────────┐
              │  PHASE 5                  │
              │  CASCADE D'INTÉGRATION    │
              │                          │
              │  • Assemblage             │
              │  • Vérif interfaces       │
              │  • Adversaire système     │
              │  • Arbitre global         │
              └────────────┬─────────────┘
                           │
                           ▼
                    ✅ LIVRABLE COMPLET
```

### 8.2 Le contrat d'interface comme relais

```
   ┌──────────────┐                ┌──────────────┐
   │   MODULE 1   │                │   MODULE 2   │
   │              │                │              │
   │  produit →   │──────────────▶ │  ← consomme  │
   │              │                │              │
   └──────┬───────┘                └───────┬──────┘
          │                                │
          │         ┌──────────┐            │
          └────────▶│ CONTRAT  │◀───────────┘
                    │INTERFACE │
                    │          │
                    │ • format │    ← créé AVANT les cascades
                    │ • champs │    ← partagé comme frozen spec
                    │ • cas    │    ← défaut bloquant si dévié
                    └──────────┘
```

### 8.3 La frozen spec comme garde-fou interne

```
   ┌─────────────────────────────────────────┐
   │              MODULE (cascade)            │
   │                                         │
   │   Itération 1 (Producteur)              │
   │        │  ↓                             │
   │   Itération 2 (Critique)                │
   │        │  ↓                             │
   │   Itération 3 (Adversaire)              │
   │        │  ↓                             │
   │   Itération 4 (Arbitre)                 │
   │        │                                │
   │        ▼                                │
   │   ┌─────────────────────────────────┐   │
   │   │  CONTRÔLE FROZEN SPEC            │   │
   │   │                                 │   │
   │   │  ☐ Invariant 1  → PRÉSENT       │   │
   │   │  ☐ Invariant 2  → PRÉSENT       │   │
   │   │  ☐ Invariant 3  → ❌ ABSENT     │   │
   │   │                                 │   │
   │   │  → ABSENT = défaut bloquant     │   │
   │   │  → Verdict CONTINUE obligatoire │   │
   │   └─────────────────────────────────┘   │
   │                                         │
   └─────────────────────────────────────────┘
```

### 8.4 Ordre topologique de production

```
   Niveau 0 (feuilles)     M1        M2        M3
                              \       │       /
   Niveau 1                    \      │      /
                                ┌─────▼─────┐
                                │    M4      │
                                └─────┬──────┘
                                      │
   Niveau 2                    ┌──────▼──────┐
                                │     M5      │
                                └──────┬──────┘
                                       │
                                ┌──────▼──────┐
                                │ INTÉGRATION  │
                                └──────┬──────┘
                                       │
                                       ▼
                                ✅ LIVRABLE
```

---

## 9. Prompts prêts à copier

> Tous les prompts sont complets, prêts à coller. Remplacez les zones entre crochets `[...]`. Chaque prompt de phase doit être exécuté dans une **nouvelle conversation vierge**.

---

### 9.1 Phase 1 — Prompt de planification modulaire

```text
Tu es un architecte logiciel. Découpe le livrable suivant en modules
indépendants, chacun sous le seuil de ~3000 lignes.

OBJECTIF GLOBAL DU LIVRABLE :
[Décris ici le livrable complet en quelques phrases.
 Ex : "Une application web de gestion de tâches avec auth,
 persistance, API REST et interface React."]

CRITÈRES DE DÉCOUPAGE :
1. Indépendance — chaque module se développe sans connaître le
   détail interne des autres.
2. Cohérence interne — un module = une responsabilité.
3. Taille bornée — maximum ~3000 lignes par module (code + tests).
4. Frontières claires — chaque frontière est définissable en interface.

Produis le plan de découpage suivant ce format :

PLAN DE DÉCOUPAGE
═════════════════
Objectif global : [une phrase]

MODULES :
  M1 : [nom] — [responsabilité] — ~[X] lignes estimées
  M2 : [nom] — [responsabilité] — ~[X] lignes
  ...

DÉPENDANCES :
  [graphe de dépendances entre modules]

ORDRE DE PRODUCTION :
  [ordre topologique recommandé : feuilles → intégration]

Règles :
- Si un module dépasse ~3000 lignes, sous-découpe-le.
- Indique explicitement les dépendances entre modules.
- Vise le minimum de modules qui respectent les critères.
- Ne produis PAS de code. Uniquement le plan.
```

---

### 9.2 Phase 2 — Prompt de création de frozen spec

```text
Tu es un ingénieur qualité. Pour le module suivant, produis une
spécification gelée (frozen spec) qui empêchera toute dérive de
simplification pendant sa production.

MODULE : [nom du module]
RESPONSABILITÉ : [description]
OBJECTIF GLOBAL DU PROJET : [une phrase]

 Liste TOUS les éléments de complexité OBLIGATOIRES de ce module :
- Les fonctionnalités critiques qui ne peuvent être simplifiées
- Les cas limites (edge cases) à gérer obligatoirement
- Les contraintes structurelles (typage, séparation des couches…)
- Les non-négociables (pas de TODO en final, pas de dépendance
  cachée, etc.)

Produis la frozen spec sous ce format :

FROZEN SPEC — Module [nom]
══════════════════════════
Contrat de complexité. Aucun élément ne peut être supprimé,
simplifié ou contourné sans validation humaine.

INVARIANTS FONCTIONNELS :
  ☐ [invariant vérifiable]
  ☐ [invariant vérifiable]
  ...

INVARIANTS STRUCTURELS :
  ☐ [invariant vérifiable]
  ...

NON-NÉGOCIABLES :
  ☐ [invariant vérifiable]
  ...

TAILLE MAX : ~3000 lignes

Règles :
- Chaque invariant doit être vérifiable par OUI/NON.
- Sois exhaustif sur la complexité légitime.
- Ne produis pas de code. Uniquement la frozen spec.
```

---

### 9.3 Phase 3 — Prompt de création de contrat d'interface

```text
Tu es un architecte d'intégration. Définis le contrat d'interface
entre les deux modules suivants.

MODULE A (producteur) : [nom] — [responsabilité]
MODULE B (consommateur) : [nom] — [responsabilité]

Ce contrat doit garantir que la sortie de A se plugue sur l'entrée
de B sans surprise.

Produis le contrat sous ce format :

CONTRAT D'INTERFACE — [Module A] → [Module B]
══════════════════════════════════════════════
A produit (output) : [description précise]
B consomme (input) : [description précise]
Format d'échange : [JSON schema / types / structure]

Invariants d'interface :
  ☐ A DOIT produire : [champs/format obligatoires]
  ☐ B DOIT gérer : [cas limites côté consommation]
  ☐ Toute déviation = défaut bloquant

Cas d'erreur :
  - [ce que A envoie si erreur]
  - [ce que B fait si entrée invalide]

Règles :
- Le format doit être non ambigu (types, champs, valeurs).
- Liste tous les cas limites de l'interface.
- Ne produis pas de code. Uniquement le contrat.
```

---

### 9.4 Phase 4 — Prompt d'itération 4 (Arbitre) avec contrôle frozen spec

> Ce prompt **remplace** le prompt d'itération 4 standard du framework de base pour les cascades de module. Il ajoute le contrôle de conformité à la frozen spec.

```text
Tu es l'arbitre final du module [nom]. Tu as trois missions :
(1) contrôler la conformité à la frozen spec,
(2) contrôler la conformité aux contrats d'interface,
(3) produire la version finale + verdict.

OBJECTIF DU MODULE :
[Colle l'objectif du module — une phrase]

FROZEN SPEC DU MODULE :
[Colle la frozen spec complète]

CONTRATS D'INTERFACE (si le module en a) :
[Colle les contrats d'interface concernés]

SYNTHÈSE COMPLÈTE DU TRAVAIL :
[Colle la synthèse orientée objectif des itérations 1, 2 et 3]

─── TEMPS 1 — CONTRÔLE FROZEN SPEC ───
Avant toute chose, vérifie la conformité à la frozen spec.
Pour chaque invariant, réponds :
  ☐ [Invariant] — PRÉSENT  |  ❌ ABSENT

─── TEMPS 2 — CONTRÔLE CONTRATS D'INTERFACE ───
Vérifie que le module respecte ses contrats d'interface.
Pour chaque invariant d'interface :
  ☐ [Invariant] — RESPECTÉ  |  ❌ VIOLÉ

─── TEMPS 3 — PRODUCTION FINALE ───
Produis la version finale du module, intégrant les corrections
des étapes 2 et 3, ET respectant TOUS les invariants ci-dessus.

─── TEMPS 4 — VERDICT JSON ───
Termine par exactement un objet JSON, sans texte après et sans
champ supplémentaire :

  {"decision":"STOP","justification":"Tous les invariants sont présents"}

Utilise "CONTINUE" si un invariant manque ou si un contrat est
violé, et identifie-le précisément dans "justification".

Règle absolue :
- Un seul invariant ABSENT ou contrat VIOLÉ → CONTINUE obligatoire.
- Le doute profite au STOP uniquement si TOUS les invariants
  sont PRÉSENTS. Sinon, c'est CONTINUE.
```

---

### 9.5 Phase 5 — Prompt d'itération 4 de la cascade d'intégration

```text
Tu es l'arbitre global du système assemblé. Tu valides que les
modules se pluguent correctement et que le tout sert l'objectif.

OBJECTIF GLOBAL DU LIVRABLE :
[Colle l'objectif global — une phrase]

MODULES ASSEMBLÉS :
  M1 : [résumé + conformité frozen spec ✓]
  M2 : [résumé + conformité frozen spec ✓]
  M3 : [résumé + conformité frozen spec ✓]
  ...

CONTRATS D'INTERFACE À VÉRIFIER :
  [Colle tous les contrats d'interface du système]

─── TEMPS 1 — VÉRIFICATION DES INTERFACES ───
Pour chaque contrat d'interface, vérifie que les modules
connectés le respectent :
  Contrat M1→M2 : ✅ RESPECTÉ  |  ❌ VIOLÉ
  Contrat M2→M3 : ✅ RESPECTÉ  |  ❌ VIOLÉ
  ...

─── TEMPS 2 — TESTS D'INTÉGRATION ───
Identifie les cas où l'assemblage peut casser :
  - Que se passe-t-il si M1 envoie une donnée inattendue à M2 ?
  - Les flux de données entre modules sont-ils cohérents ?
  - Les configurations sont-elles compatibles ?

─── TEMPS 3 — ALIGNEMENT OBJECTIF GLOBAL ───
Vérifie que le système assemblé complet sert l'objectif global.

─── TEMPS 4 — VERDICT JSON ───
Termine par exactement un objet JSON, sans texte après et sans
champ supplémentaire :

  {"decision":"STOP","justification":"Toutes les interfaces sont respectées"}

Utilise "CONTINUE" si une interface est violée ou si l'intégration
est cassée. Identifie le module responsable et l'action corrective
dans "justification".

Règle absolue :
- Un seul contrat violé → CONTINUE obligatoire + identification
  du module responsable.
- Après 5 cycles d'intégration sans succès → signal que le
  découpage initial (Phase 1) est à revoir.
```

---

## 10. Checklists de production multi-cascade

### 10.1 Checklist pré-multi-cascade (avant Phase 1)

- [ ] **Objectif global formulé** en une phrase claire.
- [ ] **Taille du livrable estimée** (si < 3000 lignes, une cascade unique suffit — voir `framework-multi-agents.md`).
- [ ] **Type de livrable identifié** (application, API, doc, agents…).
- [ ] **Critère de découpage** choisi (par couche, par feature, par domaine).

### 10.2 Checklist Phase 1 — Planification

- [ ] **Plan de découpage produit** (liste des modules avec responsabilités).
- [ ] **Chaque module sous ~3000 lignes** estimées.
- [ ] **Dépendances cartographiées** (graphe).
- [ ] **Ordre topologique** défini (feuilles → intégration).
- [ ] **Aucun module ne mélange** des responsabilités non liées.

### 10.3 Checklist Phase 2 — Frozen specs

- [ ] **Frozen spec créée pour chaque module**.
- [ ] **Chaque invariant est vérifiable** (OUI/NON, pas subjectif).
- [ ] **Tous les cas limites** légitimes sont listés.
- [ ] **Non-négociables explicites** (pas de TODO final, etc.).

### 10.4 Checklist Phase 3 — Contrats d'interface

- [ ] **Contrat défini pour chaque frontière** entre modules.
- [ ] **Format d'échange non ambigu** (types, champs, valeurs).
- [ ] **Cas d'erreur couverts** (que produit A en cas d'erreur, que fait B).
- [ ] **Contrats créés AVANT** les cascades des modules.

### 10.5 Checklist Phase 4 — Cascades de modules

Pour **chaque module** :

- [ ] **Cascade G.O.A.L. complète** exécutée (4 itérations + synthèses).
- [ ] **Modèles différents par tier** respectés (petit → très grand).
- [ ] **Synthèse orientée objectif** à chaque jonction.
- [ ] **Frozen spec vérifiée** à l'itération 4 (tous invariants PRÉSENT).
- [ ] **Contrats d'interface vérifiés** à l'itération 4 (RESPECTÉS).
- [ ] **Verdict STOP** obtenu de l'arbitre.
- [ ] **Module sous ~3000 lignes** (sinon sous-découper).

### 10.6 Checklist Phase 5 — Intégration

- [ ] **Cascade d'intégration exécutée** (4 itérations).
- [ ] **Tous les contrats d'interface validés** (RESPECTÉS).
- [ ] **Tests d'intégration** (cas limites inter-modules).
- [ ] **Alignement objectif global** vérifié.
- [ ] **Verdict STOP global** obtenu.
- [ ] **Si > 5 cycles d'intégration** → revoir le découpage Phase 1.

---

## 11. Anti-patterns spécifiques au multi-cascade

Chaque anti-pattern : **Symptôme → Cause → Parade**.

### 11.1 La dérive de simplification

| | |
|---|---|
| **Symptôme** | Le module final est moins complexe que prévu. Des fonctionnalités critiques ont disparu, simplifiées en route. |
| **Cause** | L'IA régresse vers la moyenne (solutions simples sur-représentées dans l'entraînement) + servilité (plaire plutôt que résister). |
| **Parade** | **Frozen spec** vérifiée à l'itération 4. Chaque invariant manquant = défaut bloquant. |

### 11.2 L'interface hallucinée

| | |
|---|---|
| **Symptôme** | Les modules semblent valides individuellement, mais l'assemblage échoue : un champ attendu n'existe pas, un format diffère. |
| **Cause** | L'IA a "inventé" une interface plausible qui ne correspond pas à ce que le module adjacent produit réellement. |
| **Parade** | **Contrat d'interface** créé AVANT les cascades, partagé comme frozen spec. Vérifié lors de la cascade d'intégration. |

### 11.3 Le module obèse

| | |
|---|---|
| **Symptôme** | Un module dépasse ~3000 lignes et sa qualité se dégrade (code bâclé, edge cases manqués). |
| **Cause** | Le découpage initial était insuffisant — le module regroupe en réalité plusieurs responsabilités. |
| **Parade** | **Règle de taille stricte** : si > 3000 lignes, retour Phase 1 et sous-découpage. |

### 11.4 La dépendance circulaire

| | |
|---|---|
| **Symptôme** | A dépend de B, B dépend de A. Impossible de produire les modules dans un ordre logique. |
| **Cause** | Découpage initial avec frontières mal placées. |
| **Parade** | **Ordre topologique** en Phase 1. Si cycle détecté, revoir le découpage. |

### 11.5 L'intégration interminable

| | |
|---|---|
| **Symptôme** | La cascade d'intégration dépasse 5 cycles sans convergence. |
| **Cause** | Le découpage initial est mauvais — les frontières entre modules sont arbitraires. |
| **Parade** | **Limite absolue** : après 5 cycles d'intégration, retour Phase 1 et redécoupage. C'est un signal, pas un échec. |

### 11.6 Le module orphelin

| | |
|---|---|
| **Symptôme** | Un module est produit mais jamais intégré — il flotte, sans connexion claire au système. |
| **Cause** | La planification a listé un module inutile, ou un contrat d'interface a été oublié. |
| **Parade** | **Graphe de dépendances complet** en Phase 1. Chaque module doit avoir au moins une connexion (producteur ou consommateur). |

---

### Récapitulatif des anti-patterns multi-cascade

| Anti-pattern | Parade |
|---|---|
| Dérive de simplification | Frozen spec (invariants booléens) |
| Interface hallucinée | Contrat d'interface créé avant cascades |
| Module obèse | Règle ~3000 lignes + sous-découpage |
| Dépendance circulaire | Ordre topologique Phase 1 |
| Intégration interminable | Limite 5 cycles → revoir découpage |
| Module orphelin | Graphe de dépendances complet |

---

## 12. Annexes scientifiques

### 12.1 Glossaire multi-cascade

| Terme | Définition |
|---|---|
| **Dérive de simplification** | Perte progressive de complexité légitime au fil des itérations, par régression vers la moyenne et servilité. |
| **Frozen spec** | Spécification gelée listant les invariants obligatoires d'un module, vérifiée à l'itération 4. Empêche la dérive de simplification. |
| **Contrat d'interface** | Définition formelle de la frontière entre deux modules (format, champs, cas d'erreur). Créé avant les cascades, vérifié à l'intégration. |
| **Cascade d'intégration** | G.O.A.L. Cascade complète appliquée à l'assemblage des modules. Valide les interfaces et l'alignement global. |
| **Planification modulaire** | Phase 1 : découpage du livrable en modules indépendants sous ~3000 lignes. |
| **Ordre topologique** | Ordre de production des modules respectant le graphe de dépendances (feuilles → intégration). |
| **MapReduce (appliqué au raisonnement)** | Pattern consistant à résoudre des sous-problèmes indépendamment (map) puis à les agréger (reduce). |

### 12.2 Correspondance théorie ↔ science

| Concept multi-cascade | Référence scientifique | Lien |
|---|---|---|
| Décomposition modulaire | DecompRL (arXiv) | [arXiv 2607.02390](https://arxiv.org/html/2607.02390v1) |
| Divide-and-conquer récursif | FunCoder (OpenReview) | [OpenReview](https://openreview.net/forum?id=cFqAANINgW) |
| Séparation décomposition / résolution | Guiding LLMs with D&C (arXiv) | [arXiv 2402.05359](https://arxiv.org/html/2402.05359v1) |
| Distillation de la décomposition | Apple Divide or Conquer | [GitHub](https://github.com/apple/ml-divide-or-conquer) |
| Self-consistency (MapReduce) | Self-Consistency CoT (arXiv) | [arXiv 2203.11171](https://arxiv.org/abs/2203.11171) |
| Dégradation qualité / longueur | "Can LLMs Generate Quality Code?" | [HackerNoon](https://hackernoon.com/can-llms-generate-quality-code-a-40000-line-experiment) |
| Servilité des LLMs | Uncovering Sycophancy (arXiv) | [arXiv 2508.02087](https://arxiv.org/html/2508.02087v4) |
| Spécifications auto-auteur | Model-Authored Specs (OpenReview) | [OpenReview](https://openreview.net/pdf?id=6pr7BUGkLp) |
| Prompt structuré (anti-dérive) | Structured-Prompt-Driven Dev | [Martin Fowler](https://martinfowler.com/articles/structured-prompt-driven/) |
| Brevity (qualité / longueur fichier) | "Brevity is the soul of wit" | [Awesome-Code-LLM](https://github.com/codefuse-ai/Awesome-Code-LLM) |
| Planification en 5 étapes | Chain-of-Programming | [Taylor & Francis](https://www.tandfonline.com/doi/full/10.1080/17538947.2025.2509812) |

### 12.3 Références complètes

1. **DecompRL: Solving Harder Problems by Learning Modular Code Generation** — arXiv. [https://arxiv.org/html/2607.02390v1](https://arxiv.org/html/2607.02390v1)
2. **FunCoder — Divide-and-Conquer Meets Consensus** — OpenReview. [https://openreview.net/forum?id=cFqAANINgW](https://openreview.net/forum?id=cFqAANINgW)
3. **Guiding LLMs with Divide-and-Conquer Program** — arXiv 2402.05359. [https://arxiv.org/html/2402.05359v1](https://arxiv.org/html/2402.05359v1)
4. **Self-Consistency Improves Chain of Thought Reasoning** — arXiv 2203.11171. [https://arxiv.org/abs/2203.11171](https://arxiv.org/abs/2203.11171)
5. **Apple ML — Divide or Conquer** — GitHub. [https://github.com/apple/ml-divide-or-conquer](https://github.com/apple/ml-divide-or-conquer)
6. **Can LLMs Generate Quality Code? A 40,000-Line Experiment** — HackerNoon. [https://hackernoon.com/can-llms-generate-quality-code-a-40000-line-experiment](https://hackernoon.com/can-llms-generate-quality-code-a-40000-line-experiment)
7. **Uncovering the Internal Origins of Sycophancy in LLMs** — arXiv 2508.02087. [https://arxiv.org/html/2508.02087v4](https://arxiv.org/html/2508.02087v4)
8. **Model-Authored Specifications for Reliable LLM Code Generation** — OpenReview. [https://openreview.net/pdf?id=6pr7BUGkLp](https://openreview.net/pdf?id=6pr7BUGkLp)
9. **Structured-Prompt-Driven Development (SPDD)** — Martin Fowler. [https://martinfowler.com/articles/structured-prompt-driven/](https://martinfowler.com/articles/structured-prompt-driven/)
10. **Brevity is the soul of wit: Pruning long files for code generation** — référencé dans Awesome-Code-LLM. [https://github.com/codefuse-ai/Awesome-Code-LLM](https://github.com/codefuse-ai/Awesome-Code-LLM)
11. **Chain-of-Programming (CoP) Framework** — Taylor & Francis 2025. [https://www.tandfonline.com/doi/full/10.1080/17538947.2025.2509812](https://www.tandfonline.com/doi/full/10.1080/17538947.2025.2509812)
12. **How AI May Become Deceitful, Sycophantic and Lazy** — Effective Altruism Forum. [https://forum.effectivealtruism.org/posts/shcMvRatuzZxZ3fui](https://forum.effectivealtruism.org/posts/shcMvRatuzZxZ3fui)

---

<p align="center">
  <strong>G.O.A.L. Cascade — Guide multi-cascade</strong><br>
  <em>La décomposition modulaire est la réponse scientifique à la dérive de simplification.</em><br><br>
  Aucun développeur ne code tout un projet seul.<br>
  Aucune cascade ne traite plus que ce qu'elle maîtrise.
</p>
