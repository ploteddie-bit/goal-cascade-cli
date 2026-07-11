# G.O.A.L. Cascade
## *Goal-Oriented Agentic Loop* — Framework de production multi-agents

> **Du brouillon au livrable d'excellence, par la combinaison structurée de plusieurs IA différentes.**

---

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | Juillet 2026 |
| **Statut** | Open source — prêt pour la production |
| **Licence** | MIT (voir fin de document) |
| **Auteur** | Eddie |
| **Format** | Framework opérationnel, théorie + pratique |

---

## TL;DR

> **Le problème.** Un agent IA unique, même puissant, a des angles morts, valide son propre travail et reproduit ses biais. Il plafonne.
>
> **La méthode.** G.O.A.L. Cascade orchestre **4 itérations**, chacune confiée à un **modèle différent et croissant en puissance** (du plus petit au plus grand context window). Entre chaque étape, on réinjecte **l'objectif initial + une synthèse orientée** pour empêcher la dérive.
>
> **Le résultat.** Une qualité de sortie qui tend vers l'excellence, avec des garde-fous contre les hallucinations et la divergence — le tout régi par une règle d'arrêt scientifiquement fondée.

---

## Table des matières

1. [Introduction & contexte](#1-introduction--contexte)
2. [Les 4 piliers théoriques](#2-les-4-piliers-théoriques)
3. [L'architecture des 4 itérations](#3-larchitecture-des-4-itérations)
4. [La synthèse orientée objectif](#4-la-synthèse-orientée-objectif)
5. [Prompts prêts à copier](#5-prompts-prêts-à-copier)
6. [Règles de décision & critères d'arrêt](#6-règles-de-décision--critères-darrêt)
7. [Checklists de production](#7-checklists-de-production)
8. [Anti-patterns & pièges à éviter](#8-anti-patterns--pièges-à-éviter)
9. [Diagrammes & schémas](#9-diagrammes--schémas)
10. [Guide de sélection des modèles](#10-guide-de-sélection-des-modèles)
11. [Caching & optimisation](#11-caching--optimisation)
12. [Annexes scientifiques](#12-annexes-scientifiques)
13. [Licence & contributions](#13-licence--contributions)

---

## 1. Introduction & contexte

### 1.1 Le problème

Utiliser une seule IA pour produire un livrable, c'est demander à un seul expert de tout faire : rédiger, se relire, s'auto-évaluer, corriger. Or, **personne ne juge jamais aussi bien son propre travail que celui d'un autre**. C'est encore plus vrai pour les modèles de langage :

- **Angle mort** : le modèle ne voit pas ce qu'il ne sait pas qu'il ignore.
- **Auto-approbation** : un agent qui se relit lui-même reproduit ses propres schémas et entérine ses erreurs.
- **Biais unique** : un modèle unique a un seul "point de vue" forgé par ses données d'entraînement, son alignement et son tokenizer.
- **Hallucinations invisibles** : l'inventé et le vérifié se ressemblent à la sortie ; sans regard externe, l'erreur passe.

Ajouter des itérations du **même modèle** n'aide qu'en apparence : on obtient de la redondance, pas de la diversité. Les erreurs restent *corrélées* — elles viennent des mêmes failles.

### 1.2 La thèse

> **Le multi-provider structuré élève la qualité d'un livrable vers l'excellence**, à condition de respecter quatre principes : diversité des modèles, ordonnancement en cascade, boucles bornées, et réinjection de l'objectif.

Ce framework ne se contente pas de "faire travailler plusieurs IA ensemble". Il impose une **architecture** où chaque étape a un rôle distinct, un modèle adapté, et un garde-fou contre la dérive. Chaque pièce compense la faiblesse de la précédente.

### 1.3 À qui s'adresse ce framework

- **Rédacteurs & communicants** : produire des articles, posts, rapports sourcés et relus croisé.
- **Développeurs & architectes** : concevoir du code, des architectures, des revues techniques validées.
- **Analystes & consultants** : livrer des analyses avec vérification des hypothèses et angles morts couverts.
- **Chercheurs & étudiants** : formaliser une démarche rigoureuse de production assistée par IA.

### 1.4 Ce que ce framework n'est pas

| ❌ Ce n'est pas | ✅ C'est |
|---|---|
| Du hype sur le "multi-agent" | Une méthode structurée, reproductible et bornée |
| Une garantie de perfection | Une élévation mesurable de la qualité |
| Une boîte noire automatisée | Un processus transparent, chaque étape est explicable |
| Une recette pour boucler à l'infini "jusqu'au mieux" | Un système **borné** avec critère d'arrêt explicite |
| Un substitut au jugement humain | Un amplificateur du jugement humain |
| Adapté à la création littéraire ou créative | Optimisé pour l'ingénierie et l'analyse |
| Adapté aux monolithes legacy fortement couplés | Adapté aux systèmes découplables en modules |

#### Limite de périmètre : tâches créatives

> ⚠️ **Le framework n'est pas adapté à la production créative où la forme EST le signal** (roman, copywriting, manifeste de marque, design créatif).

La synthèse orientée objectif élimine "le bruit, les tournures, la forme" pour ne garder que les idées. Or, dans l'écriture créative, **le style est le produit**. Appliquer la synthèse à un chapitre de roman broyerait la voix de l'auteur pour produire une prose plate et désincarnée.

Pour la création littéraire ou stylistique, utilisez plutôt des approches de **feedback stylistique ciblé** (critique sur la forme, pas synthèse du fond).

#### Limite de périmètre : monolithes legacy fortement couplés

> ⚠️ **Le framework multi-cascade ne fonctionne pas sur du code legacy où l'état global est omniprésent et les frontières n'existent pas.**

La décomposition modulaire (guide multi-cascade) suppose que le livrable peut être découpé en modules indépendants. Sur un monolithe legacy fortement couplé (vieux ERP, base de code de 15 ans avec état global partagé), les frontières **n'existent pas** — le LLM de Phase 1 va halluciner des découpages propres qui ne reflètent pas la réalité.

Pour du legacy indécidable, le problème est **humain d'abord** (refonte architecturale), pas IA. Aucun framework ne résout l'absence de frontières.

### 1.5 Pré-requis

Pour appliquer G.O.A.L. Cascade, vous avez besoin de :

1. **Accès à au moins 3 modèles de providers différents** (ex. Anthropic, OpenAI, Google). Voir [Section 10](#10-guide-de-sélection-des-modèles).
2. **La capacité d'effectuer des synthèses** entre les étapes (manuellement ou via un prompt dédié — fourni en [Section 5](#5-prompts-prêts-à-copier)).
3. **Un objectif de livrable formulable en une phrase claire** — c'est l'ancre de tout le système.
4. **Un humain dans la boucle** pour valider les sorties et approuver l'arrêt.

---

## 2. Les 4 piliers théoriques

G.O.A.L. Cascade repose sur quatre principes. Chacun est issu de la recherche en IA et répond à un échec précis des approches naïves. Comprendre ces piliers est essentiel : ils ne sont pas de la décoration, ce sont les **règles du jeu**.

Chaque pilier suit la même structure : **Principe → Pourquoi ça marche → Base scientifique → Piège courant**.

---

### Pilier 1 — Diversité multi-provider

> *Plusieurs modèles **réellement différents** valent mieux que plusieurs instances du même.*

#### Principe
Au lieu d'utiliser plusieurs "agents" basés sur le même modèle (ex. 3× Claude), on combine des modèles de **providers différents** (ex. Claude + GPT + Gemini). Ces modèles ont des architectures, des données d'entraînement, des méthodes d'alignement et des tokenizers distincts — donc des forces et des failles différentes.

#### Pourquoi ça marche
En machine learning, c'est le principe de l'**ensemble learning** (apprentissage d'ensemble). Le résultat clé, démontré mathématiquement :

> Si plusieurs modèles font des erreurs **non corrélées**, leur combinaison réduit considérablement le taux d'erreur final.

Deux instances du même modèle font des erreurs *corrélées* — elles ont les mêmes failles. Deux modèles de providers différents ont des failles différentes : l'erreur de l'un est rattrapée par l'autre. C'est la diversité qui crée la valeur, pas la quantité.

D'où vient cette diversité ? Pas seulement de l'architecture (le Transformer est partagé par presque tous), mais surtout de :

| Facteur | Impact sur la diversité |
|---|---|
| **Données d'entraînement** | Chaque labo a un corpus distinct → une "vision du monde" différente |
| **Alignement** | RLHF, Constitutional AI, RLAIF… chaque méthode forge un comportement propre |
| **Tokenizer** | La façon de découper le texte change la compréhension fine |
| **Optimisation** | Les fonctions objectif pendant l'entraînement diffèrent |

#### Base scientifique
- **LLM-TOPLA** (EMNLP 2024) prouve que *maximiser la diversité* entre LLMs réduit les erreurs et améliore les performances ([PDF](https://aclanthology.org/2024.findings-emnlp.698.pdf)).
- **Survey "Harnessing Multiple LLMs"** (arXiv 2025) catégorise toutes les méthodes d'ensemble ([arXiv 2502.18036](https://arxiv.org/html/2502.18036v5)).
- **DEEPEN** (NeurIPS 2024) évalue l'impact de l'hétérogénéité des architectures ([NeurIPS](https://neurips.cc/virtual/2024/poster/96435)).

#### Piège courant — la fausse diversité
Prendre deux modèles d'une même famille (ex. GPT-4 et GPT-4o) n'offre qu'une diversité *marginalle*. Visez des **providers distincts** (ex. Anthropic + OpenAI + Google) pour maximiser la décorrélation des erreurs.

---

### Pilier 2 — Cascade ascendante

> *On commence par le modèle le plus léger et on monte en puissance à chaque étape.*

#### Principe
L'itération 1 est confiée au modèle le **moins puissant** (petite fenêtre de contexte), et chaque étape suivante escalade vers un modèle **plus puissant** (jusqu'à 1–2M de tokens de contexte). Cet ordonnancement n'est pas arbitraire : il est **aligné sur la croissance du contexte** à chaque étape.

#### Pourquoi ça marche
À chaque itération, la sortie précédente devient l'entrée suivante. Le contexte grossit mécaniquement :

| Itération | Contexte nécessaire | Modèle adapté |
|---|---|---|
| 1 (Production) | Juste le prompt initial — **faible** | Petit modèle suffit |
| 2 (Vérification) | Prompt + draft 1 — **moyen** | Modèle moyen |
| 3 (Angle mort) | Prompt + draft corrigé + rapport — **grand** | Grand modèle |
| 4 (Alignement) | Prompt + synthèse complète — **très grand** | Modèle 1–2M tokens |

Démarrer petit et finir énorme, ce n'est pas un caprice — c'est **aligner la capacité du modèle sur le besoin réel du moment**. On ne mobilise pas un bulldozer pour retourner un pot de fleurs, ni une cuillère pour terrasser un terrain.

Ce pattern s'inspire de deux techniques existantes, adaptées ici à un objectif de **qualité** :
- **LLM Cascading** / **FrugalGPT** (Stanford) : petit modèle d'abord, escalade si besoin — à l'origine optimisé pour le *coût*.
- **Speculative Decoding** : un petit modèle "draft" propose, un grand modèle vérifie — à l'origine optimisé pour la *vitesse*.

G.O.A.L. Cascade réutilise ce schéma mais l'optimise pour un autre but : **la qualité du raisonnement final**.

#### Base scientifique
- **FrugalGPT** (Stanford) : cascade petit → grand, jusqu'à 98% de réduction de coût ([ResearchGate](https://www.researchgate.net/publication/370633900)).
- **Dynamic Model Routing and Cascading** (arXiv) : formalisation du cascading ([arXiv 2603.04445](https://arxiv.org/html/2603.04445v2)).
- **Speculative Decoding** survey : petit propose / grand vérifie ([arXiv 2401.07851](https://arxiv.org/html/2401.07851v2)).

#### Piège courant — le biais d'ancrage
Si le petit modèle choisit un **mauvais angle** dès l'itération 1, le grand modèle aura tendance à raffiner *dans ce mauvais angle* plutôt qu'à le remettre en question. C'est l'**ancrage** (anchoring bias). La parade : l'**itération 3 (Agent Adversaire)** est précisément conçue pour briser cet ancrage (voir [Section 3](#3-larchitecture-des-4-itérations)).

#### Garde — l'exception des tâches structurellement critiques

> ⚠️ **Pour certaines tâches, un mauvais angle initial est irrécupérable**, même avec une cascade corrective.

La cascade ascendante part du principe qu'un draft imparfait **peut être corrigé** par les itérations suivantes. C'est vrai pour la plupart des tâches. **Mais pas toutes.** Quand le choix initial détermine la structure entière du livrable, un mauvais angle n'est pas corrigeable — il est **fondateur**.

| Type de tâche | Petit modèle à l'itération 1 ? |
|---|---|
| Rédaction d'article, fonction code, rapport | ✅ Petit modèle OK (le draft est corrigé) |
| **Architecture logicielle fondamentale** | 🟡 **Modèle moyen minimum** (le squelette est fondateur) |
| **Choix de design structurel** | 🟡 **Modèle moyen minimum** (irréversible en cascade) |
| **Définition d'un schéma de données** | 🟡 **Modèle moyen minimum** (tout en découle) |

**Règle pratique** : si un changement d'angle à l'itération 1 impliquerait de **tout recommencer** (et non de corriger), alors l'itération 1 doit être confiée à un modèle au moins moyen. C'est un compromis explicite coût/qualité assumé, pas un défaut caché.

---

### Pilier 3 — Boucles bornées

> *Au-delà d'environ 5 itérations, la qualité ne monte plus — elle descend.*

#### Principe
Ajouter des itérations n'est pas toujours bon. La qualité suit une **courbe en cloche inversée** : elle monte, atteint un sommet, puis redescend. La zone optimale se situe aux alentours de **3 à 5 itérations**.

#### Pourquoi ça marche
C'est analogue à la descente de gradient en optimisation :
- **Trop peu d'itérations** → sous-optimisé (résultat brut).
- **Nombre optimal** → convergence (qualité maximale).
- **Trop d'itérations** → dérive, amplification du bruit, sur-interprétation.

La recherche a formalisé ce phénomène avec une **loi d'échelle** modélisant la qualité Q en fonction du nombre de tours T :

> ### Q(T) = a·log(T + c) − b·T

- **`a·log(T + c)`** — le terme de **gain** : convergence progressive, rendements décroissants (logarithme).
- **`−b·T`** — le terme de **fatigue** : dérive, biais qui s'accumulent, croissance linéaire.
- Le coefficient **`b > 0`** capture les effets néfastes du sur-bouclage.

La courbe qui en résulte monte, atteint un pic, puis s'effondre. Au-delà du pic, chaque itération supplémentaire *dégrade* le résultat. (Décryptage complet en [Section 12](#12-annexes-scientifiques).)

#### Base scientifique
- **"Learning to Debate: Optimal Stopping Strategies"** (IEEE) formalise Q(T) = a·log(T+c) − b·T ([IEEE](https://ieeexplore.ieee.org/document/11519273/)).
- **Literature Review of Multi-Agent Debate** (arXiv, juin 2025) confirme : *"Too many rounds introduce risks of diminishing returns or even performance degradation"* ([arXiv 2506.00066](https://arxiv.org/html/2506.00066v1)).
- **Du et al.** (MIT/Google DeepMind) : le papier fondateur du multi-agent debate ([project page](https://composable-models.github.io/llm_debate/)).

#### Piège courant — le "juste une de plus"
Le piège psychologique : *"C'est presque parfait, faisons juste une itération de plus."* C'est exactement le moment où la courbe commence à descendre. Le critère d'arrêt n'est pas humain ni subjectif — il est **structural** (voir [Section 6](#6-règles-de-décision--critères-darrêt)).

---

### Pilier 4 — Réinjection + synthèse orientée objectif

> *À chaque jonction, on repasse l'objectif initial — pas l'historique brut.*

#### Principe
Entre chaque itération, on ne transmet **pas** la sortie brute précédente. On injecte :
1. **Le prompt initial** (l'objectif, invariant, court).
2. **Une synthèse filtrée** de l'étape précédente (les idées, pas la forme).

C'est la pièce maîtresse du framework — le mécanisme qui maintient la cohérence sur l'objectif tout en cassant l'ancrage.

#### Pourquoi ça marche
Trois phénomènes l'appuient :

1. **La dégradation du contexte (*context rot*)** : plus la conversation s'allonge, plus le modèle perd l'information initiale. Réinjecter l'objectif recentre l'attention.
2. **La dilution de l'attention** : quand tout l'historique est réinjecté, l'attention se disperse sur des détails sans importance. Synthétiser force l'attention sur l'essentiel.
3. **La dérive de tâche (*task drift*)** : les LLMs s'éloignent de l'instruction originale au fil des échanges. La réinjection systématique du prompt initial est précisément le remède étudié.

En synthétisant plutôt qu'en copiant, on accomplit trois choses d'un coup :
- **Préserver la fenêtre de contexte** (pas de surcharge).
- **Recentrer sur l'objectif** (le prompt initial, invariant).
- **Casser l'ancrage** (on élimine le bruit de formulation du draft précédent).

#### Base scientifique
- **"Are you still on track? Catching LLM Task Drift with Activations"** (arXiv) prouve que les LLMs dérivent et que le re-grounding fonctionne ([arXiv 2406.00799](https://arxiv.org/html/2406.00799v5)).
- **"Context Rot"** (Chroma Research) montre la dégradation systématique avec la longueur du contexte ([Chroma](https://www.trychroma.com/research/context-rot)).
- **"Beware of the Woozle Effect"** documente la propagation des hallucinations entre agents ([ResearchGate](https://www.researchgate.net/publication/402844658)).

#### Piège courant — tout réinjecter
Réinjecter *tout* l'historique + le prompt initial semble prudent, mais cumule le context rot. La règle : **objectif initial (complet) + synthèse (filtrée), jamais l'historique brut**. La recette de synthèse est détaillée en [Section 4](#4-la-synthèse-orientée-objectif).

---

### Synthèse des 4 piliers

| Pilier | Rôle | Compense |
|---|---|---|
| **1. Diversité multi-provider** | Apporter des perspectives non corrélées | Les angles morts d'un modèle unique |
| **2. Cascade ascendante** | Aligner puissance et besoin de contexte | Le sur-coût et le sous-calibrage |
| **3. Boucles bornées** | Limiter la dérive par sur-itération | L'amplification du bruit |
| **4. Réinjection + synthèse** | Maintenir le cap sur l'objectif | La dérive de tâche et l'ancrage |

> **L'innovation de G.O.A.L. Cascade n'est pas dans les briques — elles existent. C'est dans leur combinaison : chaque pilier compense la faiblesse des trois autres.**

---

## 3. L'architecture des 4 itérations

G.O.A.L. Cascade s'exécute en **quatre étapes strictes**. Chaque étape a un rôle unique, un type de modèle dédié, et une mission précise. Les étapes ne sont **pas interchangeables**.

### 3.1 Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                    │
│   OBJECTIF INITIAL  (invariant — réinjecté à chaque jonction)      │
│                                                                    │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
             ┌───────────────────────────────┐
             │   ITÉRATION 1 — PRODUCTEUR     │  Petit modèle
             │   Génère le draft initial      │  (8–32K ctx)
             └───────────────┬───────────────┘
                             │
                  ╔══════════▼══════════╗
                  ║  SYNTHÈSE orientée  ║   ← objectif + résumé filtré
                  ║     objectif        ║
                  ╚══════════╤══════════╝
                             │
                             ▼
             ┌───────────────────────────────┐
             │   ITÉRATION 2 — CRITIQUE       │  Modèle moyen
             │   Vérifie les sources/faits    │  (64–128K ctx)
             └───────────────┬───────────────┘
                             │
                  ╔══════════▼══════════╗
                  ║  SYNTHÈSE orientée  ║
                  ║     objectif        ║
                  ╚══════════╤══════════╝
                             │
                             ▼
             ┌───────────────────────────────┐
             │   ITÉRATION 3 — ADVERSAIRE     │  Grand modèle
             │   Traque les angles morts      │  (200K ctx)
             └───────────────┬───────────────┘
                             │
                  ╔══════════▼══════════╗
                  ║  SYNTHÈSE orientée  ║
                  ║     objectif        ║
                  ╚══════════╤══════════╝
                             │
                             ▼
             ┌───────────────────────────────┐
             │   ITÉRATION 4 — ARBITRE        │  Très grand modèle
             │   Valide l'alignement + final  │  (1–2M ctx)
             └───────────────┬───────────────┘
                             │
                             ▼
                    ┌────────────────┐
                    │  STOP  →  Fin  │  Livrable validé
                    │  CONTINUE?     │  →  max 1 cycle suppl.
                    └────────────────┘
```

### 3.2 Les 4 itérations en détail

| # | Rôle | Mission | Tier de modèle | Context window | Entrée | Sortie |
|---|------|---------|---------------|----------------|--------|--------|
| **1** | **Producteur** | Générer le draft initial à partir du prompt seul | Petit | 8–32K | Prompt initial | Draft brut + sources/faits déclarés |
| **2** | **Critique** | Vérifier chaque source et affirmation factuelle ; flaguer les hallucinations | Moyen | 64–128K | Objectif + synthèse | Rapport d'erreurs point par point |
| **3** | **Adversaire** | Trouver les angles morts, biais implicites, contre-arguments légitimes | Grand | 200K | Objectif + synthèse | Contre-arguments + axes manquants |
| **4** | **Arbitre** | Évaluer l'alignement à l'objectif ; produire la version finale ; décider STOP/CONTINUE | Très grand | 1–2M | Objectif + synthèse complète | Livrable final + verdict |

### 3.3 Pourquoi cet ordre précis

L'ordre n'est pas négociable. Il suit la **croissance naturelle du contexte** :

1. **L'itération 1** a peu de contexte à traiter (juste le prompt). Un petit modèle suffit — et c'est souhaitable : on veut une **base de travail** à améliorer, pas un livrable fini. Le petit modèle pose le squelette.

2. **L'itération 2** hérite du draft (contexte moyen). Elle doit le parcourir point par point pour vérifier. C'est un travail de **forensique** qui demande un modèle plus fin.

3. **L'itération 3** cumule le draft + les corrections + les questions en suspens. Elle doit raisonner *contre* le courant dominant. C'est un travail de **critique profonde** qui demande un modèle de haut niveau.

4. **L'itération 4** englobe tout l'historique synthétisé. Elle doit vérifier l'**alignement global** avec l'objectif initial, ce qui demande de garder le prompt initial ET la synthèse complète simultanément. C'est là que la grande fenêtre de contexte (1–2M) devient nécessaire.

### 3.4 La synthèse orientée objectif : le liant entre les étapes

Entre chaque itération se trouve une **jonction critique**. C'est là que se joue la réussite ou l'échec du framework :

```
[ Sortie brute itération N ]  →  ✗ NE PAS TRANSMETTRE TEL QUEL
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │   SYNTHÈSE ORIENTÉE OBJECTIF │
                    │                             │
                    │   • Objectif initial (1 ph)  │
                    │   • Décisions clés (3-5)     │
                    │   • Incertitudes             │
                    │   • Instruction prochaine    │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    [ Entrée de l'itération N+1 ]
```

> **Sans cette synthèse, le framework dégénère : les hallucinations se propagent (effet Woozle), l'attention se dilue (context rot), et l'objectif se perd (task drift).**

La recette exacte de cette synthèse fait l'objet de la [Section 4](#4-la-synthèse-orientée-objectif).

---

## 4. La synthèse orientée objectif

La synthèse orientée objectif est la **pièce maîtresse** de G.O.A.L. Cascade. C'est elle qui distingue ce framework d'un simple enchaînement de prompts. Elle porte plusieurs noms dans la littérature — *context engineering*, *instruction reinjection*, *task grounding* — mais ici elle obéit à une recette précise.

### 4.1 Définition

> **La synthèse orientée objectif** est une représentation filtrée de l'état courant du travail, structurée autour de quatre blocs, qui est réinjectée entre chaque itération **à la place** de l'historique brut.

### 4.2 Ce qu'elle contient — et ce qu'elle exclut

| ✅ À inclure | ❌ À exclure |
|---|---|
| L'objectif initial, reformulé en **une phrase** | L'historique complet des échanges |
| Les **3 à 5 décisions clés** prises jusqu'ici | Les tournures de phrase, la formulation du draft |
| Les **incertitudes / points en suspens** | Les justifications exhaustives de chaque choix |
| **L'instruction** pour l'étape suivante | Le bruit, les digressions, les hors-sujets |

### 4.3 L'artefact exécutoire — la charge utile immuable

> ⚠️ **Exception critique à la règle de synthèse.** Ce point a été identifié par revue externe adversariale (itération 3) et corrige un défaut de conception majeur du framework.

La règle "jette la forme, garde le signal" fonctionne pour le texte narratif. **Mais pour le code, les schémas et les formules, la forme EST le signal.** On ne peut pas vérifier un bug de logique sur un résumé de 3 bullet points — l'Itération 2 (Critique) doit voir le code pour le corriger.

#### La distinction fondamentale

| Type de contenu | Traitement | Transmission |
|---|---|---|
| **Texte narratif** (idées, arguments, structure) | Synthétisé, filtré, anti-ancrage | Via la synthèse orientée objectif |
| **Artefact exécutoire** (code, schémas JSON, formules, tests) | **Non synthétisé** — transmis intact | Via la **charge utile immuable** |

#### Définition de l'artefact exécutoire

Un artefact exécutoire est tout contenu qui :
- Est **exécutable ou validable** de manière déterministe (code, tests, SQL)
- A une **syntaxe formelle** qui ne supporte pas la reformulation (schémas, types, formules)
- Doit être **modifié précisément**, pas réinterprété (patchs, configs)

Ces artefacts **ne sont jamais synthétisés**. Ils sont transmis **intacts** entre les jonctions, encapsulés séparément du texte de synthèse.

#### Le template révisé (synthèse + charge utile)

```text
══════════════════════════════════════════════════════
SYNTHÈSE ORIENTÉE OBJECTIF — Itération [N] → [N+1]
══════════════════════════════════════════════════════

OBJECTIF INITIAL : [Une phrase — l'objectif invariant]

DÉCISIONS CLÉS (3-5 max) :
  1. [Décision 1]
  2. [Décision 2]
  3. [Décision 3]

INCERTITUDES / POINTS EN SUSPENS :
  - [Ce qui n'est pas tranché / vérifié]

INSTRUCTION POUR L'ÉTAPE SUIVANTE :
  [Rôle de l'itération N+1 + ce qu'elle doit produire]

─── CHARGE UTILE IMMUABLE (ne pas synthétiser) ───

ARTEFACTS EXÉCUTOIRES :
  [Code, schémas JSON, formules, tests — transmis INTACTS]
  [L'Itération N+1 doit pouvoir les lire et les modifier]

══════════════════════════════════════════════════════
```

#### Pourquoi l'encapsulation sépare les deux mondes

```
   ┌─────────────────────────────────────────────┐
   │         JONCTION entre itérations            │
   │                                              │
   │   ┌──────────────────────────────────────┐  │
   │   │  SYNTHÈSE (texte)                     │  │
   │   │  • filtrée, anti-ancrage             │  │  ← idées, pas forme
   │   │  • recente sur l'objectif            │  │
   │   └──────────────────────────────────────┘  │
   │                                              │
   │   ┌──────────────────────────────────────┐  │
   │   │  CHARGE UTILE IMMUABLE (artefacts)    │  │
   │   │  • code, schémas, formules            │  │  ← transmis INTACT
   │   │  • non synthétisé                     │  │     (la forme = le signal)
   │   │  • encapsulé séparément               │  │
   │   └──────────────────────────────────────┘  │
   └─────────────────────────────────────────────┘
```

L'encapsulation sépare les deux mondes : le texte est synthétisé (pour contrer l'ancrage et le context rot), les artefacts sont préservés (pour permettre la vérification technique). C'est le meilleur des deux mondes.

### 4.4 Le template de synthèse narrative seule (si pas d'artefact)

```text
══════════════════════════════════════════════════════
SYNTHÈSE ORIENTÉE OBJECTIF — Itération [N] → [N+1]
══════════════════════════════════════════════════════

OBJECTIF INITIAL : [Une phrase — l'objectif invariant]

DÉCISIONS CLÉS (3-5 max) :
  1. [Décision 1]
  2. [Décision 2]
  3. [Décision 3]

INCERTITUDES / POINTS EN SUSPENS :
  - [Ce qui n'est pas tranché / vérifié]

INSTRUCTION POUR L'ÉTAPE SUIVANTE :
  [Rôle de l'itération N+1 + ce qu'elle doit produire]

══════════════════════════════════════════════════════
```

### 4.5 Pourquoi elle casse l'ancrage

L'ancrage (anchoring bias) fonctionne parce que le modèle est "pollué" par le **détail** du draft précédent — ses mots, sa structure, ses choix implicites. Si vous lui repassez une synthèse orientée vers l'objectif, vous :

1. **Éliminez le bruit** de l'itération précédente (mots, tournures, biais de formulation).
2. **Recentrez sur l'objectif** (le prompt initial, réinjecté à chaque fois).
3. **Ne gardez que le signal utile** (les idées, pas la forme).

C'est l'équivalent d'un **filtre anti-ancrage** : à chaque jonction, on "nettoie" le signal avant de le repasser.

### 4.6 Exemple concret — brut vs synthèse

#### ❌ Ce qu'il ne faut pas transmettre (historique brut)

```text
[Draft de 1200 mots avec toutes les formulations, les digressions,
les sources détaillées, les paragraphes de transition, les notes
de bas de page, les hésitations, les reformulations...]
```

Problème : le modèle suivant hérite du **style** et des **choix implicites** du draft, pas seulement du fond. Il s'ancre.

#### ✅ Ce qu'il faut transmettre (synthèse orientée objectif)

```text
OBJECTIF INITIAL : Article LinkedIn prouvant que le multi-provider
améliore la qualité des livrables IA.

DÉCISIONS CLÉS :
  1. Angle : framework méthodologique, pas hype
  2. 4 itérations (producteur → critique → adversaire → arbitre)
  3. Limite de 5 boucles justifiée par Q(T) = a·log(T+c) − b·T
  4. Réinjection du prompt initial = anti-ancrage

INCERTITUDES :
  - Le chiffre "5 boucles" est empirique, pas prouvé formellement
  - Faut-il citer FrugalGPT ou seulement le cascading ?

INSTRUCTION POUR L'ÉTAPE SUIVANTE (Critique) :
  Vérifier chaque source et affirmation factuelle. Flaguer les
  hallucinations. Ne pas réécrire — produire un rapport d'erreurs.
```

### 4.7 Comment produire la synthèse

Deux options :

- **Manuelle** : vous rédigez la synthèse vous-même entre deux itérations (recommandé pour garder le contrôle).
- **Automatisée** : un prompt dédié la génère (fourni en [Section 5, Prompt de synthèse](#5-prompts-prêts-à-copier)).

Dans les deux cas, **la discipline compte plus que l'outil** : ce qui fait marcher le framework, c'est de *toujours* synthétiser, *jamais* transmettre le brut.

---

## 5. Prompts prêts à copier

> Cette section est le cœur opérationnel du framework. Tous les prompts sont complets, prêts à coller dans n'importe quelle interface de chat IA. Remplacez simplement les zones entre crochets `[...]` par votre contenu.

Deux variantes sont fournies selon la nature du livrable :

- **Variante A — Livrable rédactionnel** (article, post, rapport, documentation)
- **Variante B — Livrable technique** (code, architecture, revue technique)

> ⚠️ **Règle absolue** : chaque itération doit être exécutée dans une **nouvelle conversation** (fenêtre vierge), avec le prompt de synthèse comme seule entrée. Ne **jamais** enchaîner les itérations dans le même fil — c'est l'isolation qui garantit l'absence d'ancrage.

---

### 5.0 Prompt de synthèse (commun aux deux variantes)

À exécuter entre chaque itération pour produire la synthèse orientée objectif.

```text
Tu es un synthétiseur. Voici l'objectif initial et le travail
produit à l'étape précédente. Produis UNE synthèse orientée
objectif selon le template suivant — rien d'autre.

OBJECTIF INITIAL :
[Colle ici le prompt initial — une phrase claire]

TRAVAIL DE L'ÉTAPE PRÉCÉDENTE :
[Colle ici la sortie brute de l'itération précédente]

Produis ta sortie STRICTEMENT sous ce format :

OBJECTIF INITIAL : [une phrase]

DÉCISIONS CLÉS (3-5 max) :
  1. [...]
  2. [...]
  3. [...]

INCERTITUDES / POINTS EN SUSPENS :
  - [...]

INSTRUCTION POUR L'ÉTAPE SUIVANTE :
  [Rôle de la prochaine itération + ce qu'elle doit produire]

Règles :
- Maximum 3 à 5 décisions clés. Sois impitoyable sur le tri.
- Élimine tout bruit : tournures, justifications exhaustives,
  digressions. Garde le signal, jette la forme.
- Si une décision est incertaine, mets-la dans "Incertitudes".
- Ne commente pas, ne justifie pas ta synthèse. Produis-la.
```

---

### 5.1 Variante A — Livrable rédactionnel

#### Itération 1 — Producteur (petit modèle)

```text
Tu es un rédacteur. Produis un premier jet du livrable suivant.

OBJECTIF :
[Décris ici ton livrable en une phrase claire et complète.
 Ex : "Un article LinkedIn qui prouve que le multi-provider
 améliore la qualité des livrables IA, ton pédagogique."]

PUBLIC CIBLE :
[Décris le lecteur. Ex : "Praticiens IA, niveau intermédiaire."]

FORMAT SOUHAITÉ :
[Ex : "Post LinkedIn, ~1500 caractères, avec accroche forte."]

CONTRAINTES :
- Sois exhaustif sur le fond, mais ne vise pas la perfection.
  Ce draft sert de base de travail, pas de livrable final.
- Pour chaque source, statistique ou affirmation factuelle,
  indique ton niveau de confiance : [HAUT] / [MOYEN] / [FAIBLE].
- Ne fabrique aucune source. Si tu n'es pas sûr, marque [FAIBLE].
- À la fin, liste explicitement toutes tes sources avec leur
  niveau de confiance.

Produis le draft maintenant.
```

#### Itération 2 — Critique des sources (modèle moyen)

```text
Tu es un vérificateur de faits (fact-checker). Ton seul job :
examiner la véracité de chaque source et affirmation.

OBJECTIF À GARDER EN TÊTE :
[Colle l'objectif initial — une phrase]

DRAFT À VÉRIFIER :
[Colle le draft de l'itération 1, OU la synthèse orientée
 objectif si elle contient le draft]

Pour CHAQUE source et affirmation factuelle du draft :
  1. Vérifie qu'elle existe réellement.
  2. Vérifie qu'elle dit bien ce qui est affirmé (pas de
     déformation, pas d'invention).
  3. Si tu ne peux pas la vérifier, marque-la HALLUCINATION POSSIBLE.

Ne RÉÉCRIS PAS le texte. Produis un RAPPORT D'ERREURS :

  ✅ [Affirmation] — VÉRIFIÉE (source : ...)
  ⚠️ [Affirmation] — NON VÉRIFIABLE
  ❌ [Affirmation] — HALLUCINATION (explication : ...)

Sois strict. Ton rôle est de traquer les hallucinations AVANT
qu'elles ne se propagent dans les étapes suivantes.
```

#### Itération 3 — Adversaire / angle mort (grand modèle)

```text
Tu es un contradicteur professionnel. Ta mission est de trouver
ce que l'auteur a oublié, ses angles morts, ses biais implicites
et les contre-arguments légitimes à sa thèse.

OBJECTIF À GARDER EN TÊTE :
[Colle l'objectif initial — une phrase]

TRAVAIL ACTUEL (draft + corrections) :
[Colle la synthèse orientée objectif des étapes 1 et 2]

Trouve et liste :
  1. ANGLES MORTS — Ce qui n'est pas traité mais devrait l'être.
  2. BIAIS IMPLICITES — Les postulats non démontrés de la thèse.
  3. CONTRE-ARGUMENTS — Les objections légitimes d'un critique.
  4. RISQUES — Les cas où la méthode proposée échouerait.

Ne sois pas d'accord par principe. Cherche les failles. Même
si la thèse est solide, trouve ce qui la fragilise.

Important : ne reformule pas le draft. Produis une critique
structurée qui servira à l'arbitre pour la version finale.
```

#### Itération 4 — Arbitre d'alignement (très grand modèle, 1–2M ctx)

```text
Tu es l'arbitre final. Tu as deux missions : (1) produire la
version finale du livrable, (2) juger si l'objectif est atteint.

OBJECTIF INITIAL :
[Colle le prompt initial — une phrase]

SYNTHÈSE COMPLÈTE DU TRAVAIL :
[Colle la synthèse orientée objectif consolidée des étapes
 1, 2 et 3]

Ta mission se déroule en deux temps :

TEMPS 1 — ÉVALUATION DE L'ALIGNEMENT
Vérifie que la version actuelle sert l'objectif initial :
  - Rien n'a été oublié ?
  - Rien n'a dérivé hors-sujet ?
  - Toutes les objections de l'adversaire sont-elles traitées ?
  - Les sources sont-elles toutes vérifiées ?

TEMPS 2 — PRODUCTION FINALE
Produis la version finale du livrable, en intégrant les
corrections de l'étape 2 et les angles morts de l'étape 3.

TEMPS 3 — VERDICT
Termine par l'un de ces deux verdicts :

  🟢 STOP — Livrable validé. [Pourquoi]
  🔴 CONTINUE — Une boucle supplémentaire est justifiée.
       [Justification précise et obligatoire]

Règle absolue : tu ne peux pas répondre CONTINUE sans une
raison concrète et documentée. Le doute profite au STOP.
```

---

### 5.2 Variante B — Livrable technique

> Les rôles sont identiques, mais les critères de vérification s'adaptent : on vérifie de la **logique**, des **tests** et des **bugs**, pas des sources documentaires.

#### Itération 1 — Producteur (petit modèle)

```text
Tu es un développeur. Produis une première implémentation de
la tâche suivante.

OBJECTIF :
[Décris la tâche technique. Ex : "Une fonction Python qui
 parse un CSV et agrège les ventes par région."]

CONTRAINTES TECHNIQUES :
- Langage : [Python / JS / etc.]
- [Toute contrainte : performance, dépendances, style]

Spécifie pour chaque fonction ou composant produit :
  - Les hypothèses que tu fais sur les entrées.
  - Les cas limites que tu as traités / ignorés.
  - Ton niveau de confiance sur la justesse : [HAUT]/[MOYEN]/[FAIBLE].

Ne cherche pas l'optimisation parfaite. Vise un code clair,
fonctionnel, qui servira de base. Produis le code maintenant.
```

#### Itération 2 — Vérificateur de logique et de tests (modèle moyen)

```text
Tu es un reviewer de code. Ton job : traquer les bugs, les
erreurs de logique et les cas limites non gérés.

OBJECTIF À GARDER EN TÊTE :
[Colle l'objectif technique initial]

CODE À VÉRIFIER :
[Colle la synthèse orientée objectif de l'étape 1, incluant
 le code]

Examine le code et produis un RAPPORT DE REVUE :

  ❌ BUG : [description] — ligne [X] — gravité [CRITIQUE/MAJEUR/MINEUR]
  ⚠️ CAS LIMITE NON GÉRÉ : [description]
  💡 RISQUE : [performance, sécurité, edge case]
  ✅ CORRECT : [ce qui est validé]

Ne réécris PAS le code. Identifie les problèmes. Pour chaque
bug, explique la cause et propose une correction ciblée.
```

#### Itération 3 — Adversaire d'architecture (grand modèle)

```text
Tu es un architecte logiciel critique. Ta mission : remettre
en question les choix de conception et trouver les failles
structurelles.

OBJECTIF À GARDER EN TÊTE :
[Colle l'objectif technique initial]

ÉTAT ACTUEL (code + revue) :
[Colle la synthèse orientée objectif des étapes 1 et 2]

Analyse et liste :
  1. FAILLES D'ARCHITECTURE — Couplage, cohésion, violations
     de principes (SOLID, etc.).
  2. ANGLES MORTS — Scénarios non couverts, échelles non
     anticipées, dépendances cachées.
  3. DÉTTE TECHNIQUE — Ce qui va coûter cher à maintenir.
  4. ALTERNATIVES — Une approche fondamentalement meilleure
     existait-elle ?

Sois exigeant. Ne valide pas par défaut. Produis une critique
structurée qui servira à l'arbitre.
```

#### Itération 4 — Arbitre technique final (très grand modèle)

```text
Tu es l'arbitre technique final. Tu produis la version finale
du livrable et tu juges si l'objectif est atteint.

OBJECTIF INITIAL :
[Colle l'objectif technique initial]

SYNTHÈSE COMPLÈTE DU TRAVAIL :
[Colle la synthèse consolidée des étapes 1, 2 et 3]

TEMPS 1 — ÉVALUATION
Vérifie l'alignement avec l'objectif :
  - Toutes les fonctionnalités demandées sont présentes ?
  - Tous les bugs de l'étape 2 sont corrigés ?
  - Les objections architecturales de l'étape 3 sont adressées ?
  - Les cas limites critiques sont gérés ?

TEMPS 2 — PRODUCTION FINALE
Produis la version finale du code, propre, commentée,
intégrant les corrections et améliorations.

TEMPS 3 — VERDICT
  🟢 STOP — Livrable validé. [Pourquoi]
  🔴 CONTINUE — Une boucle supplémentaire est justifiée.
       [Justification précise et obligatoire]

Règle absolue : pas de CONTINUE sans raison concrète.
Le doute profite au STOP.
```

---

### 5.3 Récapitulatif d'exécution

```text
┌─────────────────────────────────────────────────────────────┐
│  EXÉCUTION TYPE D'UNE CASCADE COMPLÈTE                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. Nouvelle conversation → Prompt Itération 1   [Petit]     │
│       └─ Copier la sortie                                    │
│  2. Nouvelle conversation → Prompt Synthèse      [N'importe] │
│       └─ Copier la synthèse                                   │
│  3. Nouvelle conversation → Prompt Itération 2   [Moyen]     │
│       └─ Copier la sortie                                    │
│  4. Nouvelle conversation → Prompt Synthèse      [N'importe] │
│       └─ Copier la synthèse                                   │
│  5. Nouvelle conversation → Prompt Itération 3   [Grand]     │
│       └─ Copier la sortie                                    │
│  6. Nouvelle conversation → Prompt Synthèse      [N'importe] │
│       └─ Copier la synthèse                                   │
│  7. Nouvelle conversation → Prompt Itération 4   [1-2M ctx]  │
│       └─ Lire le verdict : STOP ou CONTINUE                   │
│                                                              │
│  Si STOP → Livrable final prêt ✅                            │
│  Si CONTINUE → Max 1 cycle supplémentaire, puis STOP forcé   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. Règles de décision & critères d'arrêt

Le point le plus critique du framework. **Sans règle d'arrêt stricte, la cascade dégénère en boucle infinie qui dégrade le livrable.** Cette section définit quand s'arrêter, quand reboucler, et la limite absolue.

### 6.1 Le verdict de l'arbitre (itération 4)

L'itération 4 (Arbitre) est la **seule** étape autorisée à décider de la fin. Elle produit obligatoirement l'un de deux verdicts :

| Verdict | Signification | Action |
|---|---|---|
| 🟢 **STOP** | Le livrable est aligné à l'objectif, les objections sont traitées, les sources vérifiées. | **Fin.** Le livrable est validé. |
| 🔴 **CONTINUE** | Un point précis reste non résolu ET justifie une itération supplémentaire. | **Max 1 cycle** supplémentaire (retour à l'étape 2), puis STOP forcé. |

### 6.2 La règle du doute profitant au STOP

> **En cas d'incertitude entre STOP et CONTINUE, l'arbitre DOIT choisir STOP.**

Justification : la courbe de qualité Q(T) = a·log(T+c) − b·T montre qu'au-delà du pic, chaque itération *dégrade* le résultat. Le risque de sur-bouclage est plus grand que le risque d'un livrable légèrement imparfait. Un livrable solide aujourd'hui vaut mieux qu'un livrable "parfait" qui dérive demain.

L'arbitre ne peut répondre CONTINUE que s'il fournit une **justification concrète et documentée** — un point précis, identifiable, qui nécessite absolument un travail supplémentaire. "C'est presque parfait, on peut faire mieux" n'est **pas** une justification valide.

### 6.3 La limite absolue : 5 itérations

| Configuration | Itérations totales | Statut |
|---|---|---|
| Cascade standard | 4 | ✅ Cas nominal |
| Cascade + 1 rebouclage | 5 | ⚠️ Exception justifiée |
| Cascade + 2 rebouclages ou plus | 6+ | ❌ **Interdit** — STOP forcé obligatoire |

> **Pourquoi 5 ?** La recherche sur le multi-agent debate montre que le nombre optimal de tours varie selon la tâche, mais qu'au-delà d'un certain seuil, les rendements deviennent négatifs (voir [Pilier 3](#pilier-3--boucles-bornées)). La valeur empirique de ~5 itérations se situe dans la zone optimale de la courbe Q(T). Au-delà, la fatigue (terme −b·T) l'emporte sur le gain (terme a·log(T+c)).

### 6.4 Arbre de décision

```
                    ┌─────────────────────┐
                    │  Itération 4 finie  │
                    └──────────┬──────────┘
                               │
                    Verdict de l'arbitre ?
                               │
               ┌───────────────┴───────────────┐
               │                               │
          🟢 STOP                         🔴 CONTINUE
               │                               │
               ▼                               │
      ┌────────────────┐               ┌───────▼────────┐
      │ LIVRABLE VALIDÉ│               │ Cycle déjà > 1 │
      │  → Fin du run  │               │  (itération 5) │
      └────────────────┘               └───────┬────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │                       │
                                  OUI                     NON
                                    │                       │
                                    ▼                       ▼
                          ┌──────────────────┐    ┌──────────────────┐
                          │ STOP FORCÉ       │    │ Reboucler vers   │
                          │ Limite absolue   │    │ l'itération 2    │
                          │ atteinte (5 max) │    │ avec synthèse    │
                          └──────────────────┘    └──────────────────┘
```

### 6.5 Critères de qualité du livrable final

Avant de valider un STOP, l'arbitre (et l'humain) vérifient ces critères :

- [ ] **Alignement** : le livrable sert l'objectif initial, sans dérive.
- [ ] **Complétude** : toutes les dimensions prévues sont traitées.
- [ ] **Sources vérifiées** (variante A) / **Logique vérifiée** (variante B) : l'itération 2 n'a laissé aucune hallucination non traitée.
- [ ] **Angles morts couverts** : les objections de l'itération 3 sont intégrées ou explicitement écartées.
- [ ] **Cohérence interne** : aucune contradiction entre sections.
- [ ] **Pertinence** : pas de sur-production, pas de hors-sujet.

Si tous les critères sont remplis → STOP valide. Si un seul manque de peu → au plus un cycle, puis STOP forcé.

---

## 7. Checklists de production

Checklists actionnables pour garantir la reproductibilité. Cochez chaque item avant de passer à l'étape suivante.

### 7.1 Checklist pré-production

À valider **avant** de lancer l'itération 1.

- [ ] **Objectif formulé en une phrase claire** (test : un inconnu comprend-il la cible ?).
- [ ] **Public cible défini** (niveau, attentes, contexte).
- [ ] **Type de livrable défini** (article, code, rapport, etc. → variante A ou B).
- [ ] **Critères de succès explicites** (qu'est-ce qui rend le livrable acceptable ?).
- [ ] **3 modèles de providers différents identifiés** (petit / moyen / grand / très grand).
- [ ] **Accès confirmé** à chaque modèle sélectionné.
- [ ] **Limite de temps ou de budget définie** (pour éviter l'obsession de perfection).

### 7.2 Checklist par itération

À respecter **à chaque** itération, sans exception.

- [ ] **Nouvelle conversation vierge** démarrée (pas d'enchaînement dans le même fil).
- [ ] **Modèle adapté au tier** de cette itération (petit / moyen / grand / très grand).
- [ ] **Objectif initial réinjecté** dans le prompt (jamais implicite).
- [ ] **Synthèse orientée objectif** collée (pas la sortie brute de l'étape précédente), sauf à l'itération 1.
- [ ] **Prompt de la bonne variante** utilisé (A rédactionnel / B technique).
- [ ] **Sortie copiée et sauvegardée** avant de passer à la synthèse.

### 7.3 Checklist synthèse (entre chaque itération)

À respecter à **chaque jonction**.

- [ ] **Objectif initial présent** et reformulé en une phrase.
- [ ] **3 à 5 décisions clés maximum** (pas plus — tri impitoyable).
- [ ] **Incertitudes listées** explicitement.
- [ ] **Instruction pour l'étape suivante** claire.
- [ ] **Bruit éliminé** (pas de tournures, pas de justifications exhaustives).
- [ ] **Historique brut NON transmis**.

### 7.4 Checklist post-production / QA

À valider **après** le verdict STOP de l'arbitre.

- [ ] **Toutes les sources sont vérifiées** (variante A) — aucune mention [FAIBLE] ou HALLUCINATION non traitée.
- [ ] **Tous les bugs critiques corrigés** (variante B) — aucun ❌ CRITIQUE non résolu.
- [ ] **Les angles morts de l'étape 3 sont adressés** dans la version finale.
- [ ] **Alignement objectif validé** — lecture croisée objectif ↔ livrable final.
- [ ] **Aucune trace de Woozle** — une affirmation hallucinée n'a pas glissé jusqu'au livrable final.
- [ ] **Pas de sur-bouclage** — le run s'est arrêté à 4 ou 5 itérations maximum.
- [ ] **Validation humaine finale** — un humain a lu et approuvé.

---

## 8. Anti-patterns & pièges à éviter

Chaque anti-pattern est décrit ainsi : **Symptôme → Cause → Parade**.

---

### 8.1 Le biais d'ancrage

| | |
|---|---|
| **Symptôme** | Toutes les itérations raffinent *dans le même angle*, même si cet angle était mauvais dès le départ. Le grand modèle ne remet pas en cause le cadrage du petit. |
| **Cause** | Le modèle suivant hérite du détail (mots, structure) du draft précédent. Il s'ancrage dans la formulation au lieu de juger le fond. |
| **Parade** | **Synthèse orientée objectif** à chaque jonction (élimine le bruit de formulation). **Itération 3 (Adversaire)** dont le rôle est de briser l'ancrage en cherchant les failles. |

---

### 8.2 L'effet Woozle (propagation d'hallucinations)

| | |
|---|---|
| **Symptôme** | Une affirmation hallucinée à l'itération 1 est reprise comme vérité à l'itération 2, puis solidifiée à l'itération 3. À la fin, une invention est devenue un "fait" du livrable. |
| **Cause** | Chaque agent fait confiance à l'output du précédent sans le vérifier. Effet "téléphone arabe" : l'erreur se propage et se renforce. Nom scientifique : *Woozle Effect*. |
| **Parade** | **Itération 2 (Critique)** traque systématiquement chaque affirmation avant qu'elle ne se propague. **Niveau de confiance [HAUT]/[MOYEN]/[FAIBLE]** exigé dès l'itération 1. |

---

### 8.3 Le sur-bouclage

| | |
|---|---|
| **Symptôme** | On dépasse 5 itérations "pour atteindre la perfection". Le livrable devient *moins bon* : sur-interprété, lourd, déconnecté de l'objectif. |
| **Cause** | Le biais psychologique du *"juste une de plus"*. Or la courbe Q(T) montre qu'au-delà du pic, la qualité *décroît*. |
| **Parade** | **Limite absolue de 5 itérations**. Verdict STOP par défaut. Le critère d'arrêt est structural, pas subjectif. |

---

### 8.4 Le pourrissement du contexte (*context rot*)

| | |
|---|---|
| **Symptôme** | Le modèle "perd" l'objectif initial, rate des informations importantes, produit des sorties vagues en fin de cascade. |
| **Cause** | Trop de contexte réinjecté. L'attention se dilue sur des détails sans importance. La performance dégrade avec la longueur du contexte. |
| **Parade** | **Synthèse orientée objectif** (court, filtré) à la place de l'historique brut. **Objectif réinjecté** à chaque jonction pour recentrer l'attention. |

---

### 8.5 La fausse diversité

| | |
|---|---|
| **Symptôme** | Vous avez "plusieurs agents" mais les hallucinations et angles morts persistent comme avec un seul modèle. |
| **Cause** | Les "différents agents" sont en réalité le même modèle (ou même famille) avec des prompts différents. Leurs erreurs sont corrélées. |
| **Parade** | Exiger **des providers réellement distincts** (Anthropic + OpenAI + Google). Voir [Section 10](#10-guide-de-sélection-des-modèles). |

---

### 8.6 La convergence excessive (*mode collapse*)

| | |
|---|---|
| **Symptôme** | Les agents s'accordent trop vite, trop facilement. La critique devient molle. Le livrable manque de profondeur. |
| **Cause** | Les LLMs sont entraînés à être *helpful* et *polis*. Laissés à eux-mêmes, ils convergent plutôt qu'ils ne s'opposent. |
| **Parade** | **Itération 3 (Adversaire)** au prompt explicite : *"Ne sois pas d'accord par principe."* Rendre le désaccord **obligatoire** dans le prompt, pas optionnel. |

---

### 8.7 L'objectif flou

| | |
|---|---|
| **Symptôme** | Chaque itération interprète l'objectif différemment. Le livrable final ne ressemble pas à ce qui était voulu. |
| **Cause** | L'objectif initial n'était pas formulé en une phrase claire, ou n'a pas été réinjecté à chaque étape. |
| **Parade** | Objectif formulé **avant** l'itération 1, validé par le test du *"un inconnu comprend-il la cible ?"*. Réinjecté **tel quel** à chaque jonction. |

---

### Récapitulatif des anti-patterns

| Anti-pattern | Parade dans le framework |
|---|---|
| Biais d'ancrage | Synthèse orientée objectif + Itération 3 |
| Effet Woozle | Itération 2 (Critique) + niveaux de confiance |
| Sur-bouclage | Limite absolue de 5 + STOP par défaut |
| Context rot | Synthèse filtrée (jamais l'historique brut) |
| Fausse diversité | Providers réellement distincts |
| Convergence excessive | Adversaire obligatoire (prompt "ne sois pas d'accord") |
| Objectif flou | Formulation stricte + réinjection systématique |

---

## 9. Diagrammes & schémas

Référence visuelle des concepts clés du framework.

### 9.1 La cascade ascendante

```
   PUISSANCE DU MODÈLE
   ▲
   │                                          ┌──────────────┐
   │                                          │  ITÉRATION 4  │
   │                                          │   ARBITRE     │  Très grand
   │                                          │  1–2M ctx     │
   │                          ┌──────────────┐└──────────────┘
   │                          │  ITÉRATION 3  │
   │                          │  ADVERSAIRE   │  Grand
   │                          │   200K ctx    │
   │          ┌──────────────┐└──────────────┘
   │          │  ITÉRATION 2  │
   │          │   CRITIQUE    │  Moyen
   │          │   64–128K     │
   │┌────────┐└──────────────┘
   ││ ITÉR 1 │
   ││PRODUC. │  Petit
   ││ 8–32K  │
   │└────────┘
   └──────────────────────────────────────────────────────▶ TEMPS
```

### 9.2 La courbe qualité / nombre de boucles

```
   QUALITÉ Q(T)
   ▲
   │            .─────.        ← PIC (zone optimale : ~3–5 itérations)
   │          .         .
   │        .             .
   │       .               .    ← Terme de gain : a·log(T+c)
   │      .                  .     (convergence progressive)
   │     .                     .
   │    .                        .  ← Terme de fatigue : −b·T
   │   .                           .   (dérive, dégradation)
   │  .                              .
   │ .                                  .___ decay
   │
   └──────┬──────┬──────┬──────┬──────┬──────▶ NOMBRE D'ITÉRATIONS (T)
          1      2      3      4      5      6+

          │← zone productive →│← zone de →│
                                 dérive     │← interdit →
```

> **Lecture** : jusqu'à ~5 itérations, la qualité monte (le gain l'emporte). Au-delà, la fatigue l'emporte et la qualité décline. La zone au-delà de 5 est **interdite** par le framework.

### 9.3 La croissance du contexte par itération

```
   TAILLE DU CONTEXTE NÉCESSAIRE
   ▲
   │                          ┌─────────────────┐
   │                          │  Itération 4     │  Prompt + synthèse
   │                          │  complète → 1-2M │  complète
   │            ┌─────────────┘                  │
   │            │  Itération 3                    │
   │            │  draft + revue → 200K           │
   │  ┌─────────┘                                │
   │  │  Itération 2                              │
   │  │  prompt + draft → 64-128K                 │
   │  │                                           │
   │  │  Itération 1                              │
   │  │  prompt seul → 8-32K                      │
   │──┴───────────────────────────────────────▶  ITÉRATIONS
```

> **Lecture** : à chaque étape, le contexte grossit mécaniquement (la sortie devient l'entrée). La cascade ascendante aligne la puissance du modèle sur ce besoin croissant.

### 9.4 Le flux complet d'une cascade

```
   ┌─────────────────────────────────────────────────────────────┐
   │                  OBJECTIF INITIAL (invariant)                │
   └──────────────────────────┬──────────────────────────────────┘
                              │
   ┌──────────────────────────▼──────────────────────────────────┐
   │  ÉTAPE 1 : [Petit modèle]   PRODUCTEUR                       │
   │  "Génère le draft + niveau de confiance par source"          │
   └──────────────────────────┬──────────────────────────────────┘
                              │
                  ╔══════════▼══════════╗
                  ║ SYNTHÈSE OBJECTIF    ║  ← filtre anti-ancrage
                  ╚══════════╤══════════╝
                              │
   ┌──────────────────────────▼──────────────────────────────────┐
   │  ÉTAPE 2 : [Moyen modèle]   CRITIQUE                         │
   │  "Vérifie chaque source. Traque les hallucinations"          │
   └──────────────────────────┬──────────────────────────────────┘
                              │
                  ╔══════════▼══════════╗
                  ║ SYNTHÈSE OBJECTIF    ║
                  ╚══════════╤══════════╝
                              │
   ┌──────────────────────────▼──────────────────────────────────┐
   │  ÉTAPE 3 : [Grand modèle]  ADVERSAIRE                        │
   │  "Trouve angles morts + contre-arguments. Désaccord requis"  │
   └──────────────────────────┬──────────────────────────────────┘
                              │
                  ╔══════════▼══════════╗
                  ║ SYNTHÈSE OBJECTIF    ║
                  ╚══════════╤══════════╝
                              │
   ┌──────────────────────────▼──────────────────────────────────┐
   │  ÉTAPE 4 : [1-2M ctx]    ARBITRE                             │
   │  "Valide alignement. Produis final. STOP ou CONTINUE ?"      │
   └──────────────────────────┬──────────────────────────────────┘
                              │
                 ┌────────────┴────────────┐
                 ▼                         ▼
          🟢 STOP                    🔴 CONTINUE
        (doute profite                (justification
         au STOP)                      précise requise)
                 │                         │
                 ▼                         ▼
        ✅ LIVRABLE              Max 1 cycle → STOP forcé
```

---

## 10. Guide de sélection des modèles

### 10.1 Les 4 tiers

Le framework nécessite 4 rôles, idéalement servis par 4 modèles de providers **différents**. Voici une cartographie indicative.

| Tier | Itération | Context window visé | Exemples indicatifs (2026) |
|---|---|---|---|
| **1 — Petit** | Producteur | 8–32K | Haiku-class, Mini-class, modèles légers open source |
| **2 — Moyen** | Critique | 64–128K | Sonnet-class, GPT-4o-class, modèles mid-tier |
| **3 — Grand** | Adversaire | 200K | Opus-class, GPT-4-class, modèles flagship |
| **4 — Très grand** | Arbitre | 1–2M | Gemini-class (long context), modèles 1M+ |

> ⚠️ **Le paysage des modèles évolue très vite.** Ce tableau est indicatif pour 2026. Adaptez-le selon les disponibilités du moment. L'important n'est pas le nom du modèle, mais le **respect des 4 tiers** et la **diversité des providers**.

### 10.2 La règle de diversité provider

C'est la règle la plus importante de cette section :

> **Ne prenez pas deux modèles de la même famille pour des rôles différents.**

| ❌ Mauvaise diversité | ✅ Bonne diversité |
|---|---|
| Itération 1 : GPT-4o-mini | Itération 1 : Haiku |
| Itération 2 : GPT-4o | Itération 2 : GPT-4o |
| Itération 3 : GPT-4 | Itération 3 : Gemini Pro |
| Itération 4 : GPT-4 (long ctx) | Itération 4 : Gemini (1-2M) |

La colonne de gauche n'offre qu'une diversité *marginale* (même labo, même alignement, données similaires). La colonne de droite maximise la décorrélation des erreurs.

### 10.3 Tableau de combinaisons recommandées

Combinaisons suggérées (à adapter selon vos accès) :

| Combinaison | Petit | Moyen | Grand | Très grand | Diversité |
|---|---|---|---|---|---|
| **A** | Haiku | GPT-4o-mini | Opus | Gemini 1-2M | 🟢 Excellente (3 providers) |
| **B** | Gemini Flash | Haiku | GPT-4 | Gemini 1-2M | 🟢 Bonne (3 providers) |
| **C** | Mini-class | Sonnet | Opus | Gemini 1-2M | 🟡 Correcte (2 providers) |
| **D** | GPT-4o-mini | Haiku | GPT-4 | Gemini 1-2M | 🟢 Bonne (3 providers) |

### 10.4 Si vous n'avez accès qu'à un seul provider

Si vous n'avez qu'un seul provider, vous perdez une partie du bénéfice du framework. Deux options de dégradation :

- **Option 1 — Diversité de modèles** : utilisez les versions *small / medium / large* du même provider. C'est mieux que rien, mais les erreurs resteront corrélées.
- **Option 2 — Diversité de prompting** : utilisez le même modèle mais avec des *personae* radicalement différents dans les prompts. Compense la faible diversité par un contraste de rôle forcé.

Dans les deux cas, **l'itération 3 (Adversaire) devient encore plus critique** car elle est votre seule défense contre l'ancrage.

---

## 11. Caching & optimisation

G.O.A.L. Cascade multiplie les appels (4 itérations × plusieurs modèles, plus les synthèses). Le coût et la latence deviennent un vrai sujet. Deux mécanismes de cache permettent d'optimiser massivement — mais ils ont des **rôles radicalement différents**, et l'un d'eux est **dangereux** s'il est mal utilisé.

### 11.1 Les deux types de cache

#### Cache exact (prompt caching / KV cache)

C'est une fonctionnalité **native des providers**. Le provider stocke le calcul interne (les *KV tensors*) des tokens déjà vus, pour ne pas les recalculer. Ne fonctionne que si le **préfixe est identique au token près**.

| Provider | Mécanisme | Seuil minimum | Épargne coût | Épargne latence |
|---|---|---|---|---|
| **Anthropic** | Explicite (`cache_control`) | ~1 024 tokens | jusqu'à **90 %** | jusqu'à **85 %** |
| **OpenAI** | Automatique (pas d'opt-in) | 1 024 tokens | ~**50 %** | modérée |
| **Google** | Implicite + explicite | variable | significative | significative |

#### Cache sémantique (semantic cache)

C'est une couche **externe** (ex : GPTCache, Redis) qui compare votre requête avec des requêtes déjà posées via des **embeddings**. Si deux requêtes sont *sémantiquement proches* (cosinus ≥ seuil), on retourne la réponse cachée — même si le texte diffère.

| Métrique | Valeur | Source |
|---|---|---|
| Hit rate | jusqu'à **68,8 %** | [arXiv 2411.05276](https://arxiv.org/html/2411.05276v2) |
| Précision des hits | > **97 %** | idem |
| Réduction de latence | **40–50 %** | [JSAER 2024](https://jsaer.com/download/vol-11-iss-9-2024/JSAER2024-11-9-155-164.pdf) |
| Référence open-source | **GPTCache** | [OpenReview](https://openreview.net/pdf?id=ivwM8NwM4Z) |

**Le risque** : le cache sémantique peut produire des *silent failures* — des hits faux positifs où une réponse proche mais incorrecte est servie.

### 11.2 La règle d'or : exact dedans, sémantique dehors

```
┌──────────────────────────────────────────────────────────────┐
│                                                                │
│  CACHE EXACT  →  ✅ À L'INTÉRIEUR d'une cascade                │
│                   Actif par défaut. Optimise les préfixes      │
│                   stables (objectif, frozen spec, interfaces)  │
│                                                                │
│  CACHE SÉMANTIQUE  →  ✅ À L'EXTÉRIEUR des cascades            │
│                        Entre projets / runs différents.        │
│                        JAMAIS à l'intérieur d'une cascade.     │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

#### Pourquoi le cache exact est parfait pour la cascade

Le framework réinjecte **l'objectif initial + la frozen spec + les contrats d'interface** à chaque itération. Ces éléments sont des **préfixes stables** — exactement ce que le cache exact optimise.

```
┌─────────────────────────────────────────────────────┐
│  PRÉFIXE STABLE (réinjecté à chaque itération)       │
│  ┌───────────────────────────────────────────────┐  │
│  │ OBJECTIF INITIAL : [...]                       │  │ ← CACHEABLE (jusqu'à 90%)
│  │ FROZEN SPEC : [...]                            │  │ ← CACHEABLE
│  │ CONTRATS D'INTERFACE : [...]                   │  │ ← CACHEABLE
│  └───────────────────────────────────────────────┘  │
│                                                       │
│  PARTIE VARIABLE (unique à chaque itération)          │
│  ┌───────────────────────────────────────────────┐  │
│  │ SYNTHÈSE ORIENTÉE OBJECTIF de l'étape préc.    │  │ ← NON CACHEABLE
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**Recommandation** : activer le cache exact par défaut sur toutes les cascades. C'est un gain quasi gratuit.

#### Pourquoi le cache sémantique est dangereux à l'intérieur d'une cascade

Le **piège majeur** : le cache sémantique peut **court-circuiter la diversité multi-provider** — le Pilier 1 du framework.

| Risque du cache sémantique dans la cascade | Impact |
|---|---|
| Renvoie une réponse de l'agent A à l'agent B | **Tue la diversité** multi-provider |
| Hit faux positif (*silent failure*) | Propage une erreur comme l'effet Woozle |
| Cache une synthèse intermédiaire | Fige un état qui devait évoluer |

**À l'intérieur d'une cascade**, chaque itération doit produire un travail *nouveau*. Le cache sémantique court-circuiterait ce que la cascade cherche précisément à obtenir.

**À l'extérieur des cascades** (entre projets, entre runs sur des sujets proches), la réutilisation sémantique est légitime et rentable.

### 11.3 Le cache sémantique comme détecteur de dérive — usage original

C'est l'usage le plus novateur du cache sémantique dans le framework. Au lieu de l'utiliser pour *servir* une réponse, on l'utilise pour **mesurer la similarité** entre itérations successives et détecter que la cascade tourne à vide.

#### Le principe

> **Si deux itérations successives produisent des réponses sémantiquement identiques (similarité d'embedding ≥ seuil), c'est le signal que la cascade n'avance plus.** Soit le modèle s'est ancré et ne fait que reformuler, soit l'itération n'apporte rien de nouveau.

#### La mécanique

```
   Itération N   ──▶  embedding A
                          │
                          │   similarité cosinus(A, B)
                          ▼
   Itération N+1 ──▶  embedding B
                          │
                          ▼
              ┌───────────────────────┐
              │  cos(A,B) ≥ seuil ?   │
              │                       │
              │  OUI → DÉRIVE détectée│  → STOP anticipé
              │       (ancrage ou     │     (la cascade tourne à vide)
              │        convergence)    │
              │                       │
              │  NON → Progression    │  → continuer normalement
              └───────────────────────┘
```

#### Les deux dérives détectées

| Similarité élevée entre… | Diagnostic | Action |
|---|---|---|
| Itération N et N+1 | **Ancrage** — le modèle reformule sans avancer | STOP anticipé, la cascade n'apporte plus rien |
| Itérations 1, 2, 3 (toutes) | **Convergence excessive** — les agents s'accordent trop vite, la diversité est perdue | STOP, la cascade a échoué à produire de la diversité |

#### Le seuil de similarité

| cos(A,B) | Interprétation | Action recommandée |
|---|---|---|
| ≥ **0,95** | Réponses quasi identiques | 🔴 STOP — la cascade tourne à vide |
| **0,85 – 0,95** | Forte similarité, possible reformulation | 🟡 Alerte — vérifier si l'itération a apporté du nouveau |
| **0,70 – 0,85** | Progresse dans la même direction | ✅ Normal |
| < **0,70** | Forte divergence (normal pour l'adversaire) | ✅ Attendu (spécialement itération 3) |

> **Note** : ces seuils sont empiriques. Ils dépendent du modèle d'embedding utilisé. Calibrez-les sur vos premiers runs.

#### Pourquoi c'est élégant

On réutilise l'**infrastructure** du cache sémantique (embeddings + calcul de similarité) pour un **objectif totalement différent** : le diagnostic qualité. Au lieu de *servir* la réponse la plus proche, on *mesure* la distance entre les itérations pour savoir si le système converge ou dérive.

C'est l'équivalent d'un **tachymètre** : la similarité entre itérations est la vitesse de progression de la cascade. Si elle tombe à zéro, on est à l'arrêt — même si le moteur tourne.

### 11.4 Diagramme : où chaque cache s'applique

```
   ┌─────────────────────────────────────────────────────────────┐
   │                    CACHE EXACT (dedans)                      │
   │                                                              │
   │   ┌────────────┐  ┌────────────┐  ┌────────────┐            │
   │   │ Cascade A  │  │ Cascade B  │  │ Cascade C  │            │
   │   │            │  │            │  │            │            │
   │   │ préfixe    │  │ préfixe    │  │ préfixe    │            │
   │   │ stable ✓   │  │ stable ✓   │  │ stable ✓   │            │
   │   └─────┬──────┘  └─────┬──────┘  └─────┬──────┘            │
   │         │               │               │                    │
   │         └───────────────┼───────────────┘                    │
   │                         │                                    │
   └─────────────────────────┼────────────────────────────────────┘
                             │
   ┌─────────────────────────┼────────────────────────────────────┐
   │                  CACHE SÉMANTIQUE (dehors)                    │
   │                         │                                     │
   │   ┌─────────────────────▼──────────────────────┐             │
   │   │  Réutilisation transverse entre projets     │             │
   │   │  + DÉTECTION DE DÉRIVE (similarité intra)   │             │
   │   └─────────────────────────────────────────────┘             │
   └───────────────────────────────────────────────────────────────┘
```

### 11.5 Activation par provider

#### Anthropic
```python
# cache_control explicite sur le préfixe stable
messages = [
    {
        "role": "user",
        "content": [
            {"type": "text", "text": objectif_initial + frozen_spec,
             "cache_control": {"type": "ephemeral"}},  # ← préfixe caché
            {"type": "text", "text": synthèse_variable},            # ← non caché
        ]
    }
]
```
Économie : jusqu'à **90 %** sur le préfixe. Latence : −85 %.

#### OpenAI
Automatique pour les prompts > 1 024 tokens. Placez le préfixe stable **en début de prompt**. Aucune configuration nécessaire. Économie : ~50 %.

#### Google (Gemini)
Implicite + explicite. Placez le contenu volumineux et stable en début de prompt pour maximiser les hits implicites. Documentation : [Context Caching](https://ai.google.dev/gemini-api/docs/caching).

### 11.6 Anti-pattern : le sémantique qui tue la diversité

| | |
|---|---|
| **Symptôme** | Vous activez un cache sémantique entre les itérations pour "aller plus vite". Résultat : la qualité du livrable final est dégradée, équivalente à un modèle unique. |
| **Cause** | Le cache sémantique renvoie une réponse d'un agent précédent (potentiellement d'un autre provider) au lieu de faire travailler un modèle différent. La diversité — valeur centrale du framework — est détruite. |
| **Parade** | **Jamais de cache sémantique à l'intérieur d'une cascade.** Réservez-le à la réutilisation entre projets et à la détection de dérive. |

---

## 12. Annexes scientifiques

### 12.1 La formule clé décryptée

> ### Q(T) = a·log(T + c) − b·T

Cette formule modélise la qualité Q d'un livrable en fonction du nombre d'itérations T. Elle est issue de la recherche sur les stratégies d'arrêt optimal en multi-agent debate.

| Terme | Signification | Effet |
|---|---|---|
| `Q(T)` | Qualité du livrable après T itérations | Ce qu'on veut maximiser |
| `a·log(T + c)` | Terme de **gain** | Convergence progressive — rendements décroissants (forme logarithme). `a` est le coefficient de gain. |
| `c` | Constante de décalage | Ajuste le point de départ |
| `−b·T` | Terme de **fatigue** | Dérive, biais accumulés, amplification du bruit — croissance *linéaire*. `b > 0`. |

**Dynamique** : au début, le terme de gain (logarithmique) domine → la qualité monte. Puis le terme de fatigue (linéaire) rattrape et dépasse → la qualité redescend. Le pic de la courbe définit le **nombre optimal d'itérations**.

**Lien avec le framework** : ce pic se situe empiriquement autour de 3–5 itérations selon la tâche. C'est ce qui justifie la **limite absolue de 5** dans G.O.A.L. Cascade.

### 12.2 Glossaire

| Terme | Définition |
|---|---|
| **Ensemble learning** | Technique de ML consistant à combiner plusieurs modèles pour réduire les erreurs, surtout quand leurs erreurs sont non corrélées. |
| **LLM Cascading** | Enchaînement séquentiel de modèles du plus petit au plus grand, avec escalade conditionnelle. Optimisé à l'origine pour le coût (FrugalGPT). |
| **Speculative decoding** | Technique d'accélération : un petit modèle "draft" propose, un grand modèle vérifie en parallèle. Sans perte de qualité. |
| **Task drift** | Phénomène où un LLM s'éloigne progressivement de l'instruction initiale au fil d'une conversation. |
| **Context rot** | Dégradation de la performance d'un LLM quand la longueur du contexte augmente. |
| **Woozle effect** | Propagation d'une information non vérifiée (ou hallucinée) qui devient un "fait" par répétition d'agent à agent. |
| **Anchoring bias** (biais d'ancrage) | Tendance à s'en tenir à la première information reçue (ici, le cadrage du premier draft) même quand elle est imparfaite. |
| **Mode collapse** | Phénomène où des agents multi-modèles convergent trop vite vers une réponse commune, perdant la diversité qui faisait leur force. |
| **Synthèse orientée objectif** | Représentation filtrée de l'état du travail (4 blocs) réinjectée entre les itérations, à la place de l'historique brut. C'est le mécanisme central de G.O.A.L. Cascade. |

### 12.3 Correspondance théorie ↔ science

| Concept du framework | Référence scientifique | Lien |
|---|---|---|
| Diversité multi-provider | LLM-TOPLA (EMNLP 2024) | [PDF](https://aclanthology.org/2024.findings-emnlp.698.pdf) |
| Diversité multi-provider | Survey LLM Ensemble (arXiv 2025) | [arXiv 2502.18036](https://arxiv.org/html/2502.18036v5) |
| Hétérogénéité des architectures | DEEPEN (NeurIPS 2024) | [NeurIPS](https://neurips.cc/virtual/2024/poster/96435) |
| Cascade petit → grand | FrugalGPT (Stanford) | [ResearchGate](https://www.researchgate.net/publication/370633900) |
| Cascade / routing | Dynamic Model Routing (arXiv) | [arXiv 2603.04445](https://arxiv.org/html/2603.04445v2) |
| Petit propose / grand vérifie | Speculative Decoding survey | [arXiv 2401.07851](https://arxiv.org/html/2401.07851v2) |
| Loi d'arrêt optimal Q(T) | Optimal Stopping Strategies (IEEE) | [IEEE](https://ieeexplore.ieee.org/document/11519273/) |
| Dérive des rendements | Lit. Review Multi-Agent Debate (arXiv) | [arXiv 2506.00066](https://arxiv.org/html/2506.00066v1) |
| Multi-agent debate (fondateur) | Du et al. (MIT/DeepMind) | [Project page](https://composable-models.github.io/llm_debate/) |
| Task drift | Catching LLM Task Drift (arXiv) | [arXiv 2406.00799](https://arxiv.org/html/2406.00799v5) |
| Context rot | Chroma Research | [Chroma](https://www.trychroma.com/research/context-rot) |
| Propagation d'hallucinations | Woozle Effect (ResearchGate) | [ResearchGate](https://www.researchgate.net/publication/402844658) |
| Débat adversarial & vote | Adversarial Debate (MDPI) | [MDPI](https://www.mdpi.com/2076-3417/15/7/3676) |
| Débat éparse et égal | CortexDebate (ACL 2025) | [ACL Anthology](https://aclanthology.org/2025.findings-acl.495.pdf) |
| Cadre théorique multi-LLM | Multi-LLM Debate Framework (NeurIPS 2024) | [NeurIPS](https://neurips.cc/virtual/2024/poster/93363) |
| Cache sémantique (référence) | GPTCache (OpenReview) | [OpenReview](https://openreview.net/pdf?id=ivwM8NwM4Z) |
| Cache sémantique (benchmark) | Semantic Embedding Caching (arXiv) | [arXiv 2411.05276](https://arxiv.org/html/2411.05276v2) |
| Cache sémantique (revue) | Semantic Caching Review (JSAER) | [JSAER](https://jsaer.com/download/vol-11-iss-9-2024/JSAER2024-11-9-155-164.pdf) |
| Cache exact (prompt caching) | Prompt Caching Infrastructure (Introl) | [Introl](https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025) |

### 12.4 Références complètes

1. **LLM-TOPLA: Efficient LLM Ensemble by Maximising Diversity** — EMNLP 2024 Findings. [https://aclanthology.org/2024.findings-emnlp.698.pdf](https://aclanthology.org/2024.findings-emnlp.698.pdf)
2. **Harnessing Multiple Large Language Models: A Survey on LLM Ensemble** — arXiv 2502.18036. [https://arxiv.org/html/2502.18036v5](https://arxiv.org/html/2502.18036v5)
3. **DEEPEN: Ensemble Learning for Heterogeneous LLMs** — NeurIPS 2024. [https://neurips.cc/virtual/2024/poster/96435](https://neurips.cc/virtual/2024/poster/96435)
4. **FrugalGPT: How to Use LLMs While Reducing Cost and Improving Performance** — Chen, Zaharia et al., Stanford. [https://www.researchgate.net/publication/370633900](https://www.researchgate.net/publication/370633900)
5. **Dynamic Model Routing and Cascading for Efficient LLM Inference** — arXiv 2603.04445. [https://arxiv.org/html/2603.04445v2](https://arxiv.org/html/2603.04445v2)
6. **A Comprehensive Survey of Speculative Decoding** — arXiv 2401.07851. [https://arxiv.org/html/2401.07851v2](https://arxiv.org/html/2401.07851v2)
7. **Learning to Debate: Optimal Stopping Strategies for Multi-Agent Debate** — IEEE. [https://ieeexplore.ieee.org/document/11519273/](https://ieeexplore.ieee.org/document/11519273/)
8. **Literature Review of Multi-Agent Debate for Problem-Solving** — arXiv 2506.00066, juin 2025. [https://arxiv.org/html/2506.00066v1](https://arxiv.org/html/2506.00066v1)
9. **Improving Factuality and Reasoning through Multiagent Debate** — Du et al. [https://composable-models.github.io/llm_debate/](https://composable-models.github.io/llm_debate/)
10. **Are you still on track? Catching LLM Task Drift with Activations** — arXiv 2406.00799. [https://arxiv.org/html/2406.00799v5](https://arxiv.org/html/2406.00799v5)
11. **Context Rot: How Increasing Input Tokens Impacts LLM Performance** — Chroma Research. [https://www.trychroma.com/research/context-rot](https://www.trychroma.com/research/context-rot)
12. **Beware of the Woozle Effect: Hallucination Propagation in Multi-Agent Debate** — ResearchGate. [https://www.researchgate.net/publication/402844658](https://www.researchgate.net/publication/402844658)
13. **Analyzing Error Propagation in Multi-Agent LLM Systems** — arXiv. [https://arxiv.org/html/2606.07937v1](https://arxiv.org/html/2606.07937v1)
14. **Adversarial Debate and Voting Mechanisms in LLM-Based Multi-Agent Systems** — MDPI Applied Sciences. [https://www.mdpi.com/2076-3417/15/7/3676](https://www.mdpi.com/2076-3417/15/7/3676)
15. **CortexDebate: Debating Sparsely and Equally** — ACL Findings 2025. [https://aclanthology.org/2025.findings-acl.495.pdf](https://aclanthology.org/2025.findings-acl.495.pdf)
16. **Multi-LLM Debate: Framework, Principles, and Interventions** — NeurIPS 2024. [https://neurips.cc/virtual/2024/poster/93363](https://neurips.cc/virtual/2024/poster/93363)
17. **GPTCache: An Open-Source Semantic Cache for LLM Applications** — OpenReview. [https://openreview.net/pdf?id=ivwM8NwM4Z](https://openreview.net/pdf?id=ivwM8NwM4Z)
18. **Reducing LLM Costs and Latency via Semantic Embedding Caching** — arXiv 2411.05276. [https://arxiv.org/html/2411.05276v2](https://arxiv.org/html/2411.05276v2)
19. **Semantic Caching for LLM Applications: A Review** — JSAER, Vol 11, 2024. [https://jsaer.com/download/vol-11-iss-9-2024/JSAER2024-11-9-155-164.pdf](https://jsaer.com/download/vol-11-iss-9-2024/JSAER2024-11-9-155-164.pdf)
20. **Prompt Caching Infrastructure: Reducing LLM Costs and Latency** — Introl, 2025. [https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025](https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025)

---

## 13. Licence & contributions

### Licence MIT

```
MIT License

Copyright (c) 2026 Eddie

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Contributions

Ce framework est ouvert aux contributions. Les axes d'amélioration bienvenus :

- **Études de cas** : retours d'usage sur des livrables réels.
- **Combinaisons de modèles** testées et leurs résultats.
- **Adaptation à de nouveaux types de livrables** (audio, visuel, data).
- **Affinement du seuil de boucles** selon les types de tâches.

### Citation

Si vous utilisez G.O.A.L. Cascade dans un travail public, merci de citer :

```text
G.O.A.L. Cascade — Goal-Oriented Agentic Loop
Framework de production multi-agents
Eddie, v1.0, Juillet 2026
Licence MIT
```

---

<p align="center">
  <strong>G.O.A.L. Cascade</strong><br>
  <em>Du brouillon au livrable d'excellence.</em><br><br>
  Chaque technique existe isolément. L'innovation est dans leur combinaison :<br>
  chaque étape corrige la faille de la précédente.
</p>






