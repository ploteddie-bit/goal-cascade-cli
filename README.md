# G.O.A.L. Cascade CLI

Prototype exécutable du framework **Goal-Oriented Agentic Loop**.

## Contrat production V2

La source de vérité du produit est la [spécification d'implémentation V2](docs/specs/goal-cascade-implementation-v2.md), complétée par :

- le [cadre multi-agents](docs/specs/framework-multi-agents.md) ;
- le [guide multi-cascade](docs/specs/goal-cascade-multi-cascade.md) ;
- le [plan chirurgical de référence](docs/specs/reference-qwen-plan-chirurgical.md) ;
- l'[addendum normatif du chef d'orchestre IA](docs/specs/addendum-chef-orchestre-ia.md).

La version actuelle `0.1.0` est une **fondation partielle**. Elle n'est ni la
V2 complète ni un livrable de production. Le chef d'orchestre IA persistant,
LangGraph/SQLite, le multi-provider réel, les budgets, la dérive, le
versionnage, la découverte guidée et le multi-cascade restent à implémenter.

Le jalon actuel fournit une cascade unique avec :

- quatre rôles principaux : producteur, critique, adversaire et arbitre ;
- une synthèse orientée objectif entre les rôles ;
- un provider de synthèse distinct avec un modèle small/cheap explicite ;
- la préservation séparée des blocs de code et autres artefacts techniques ;
- un verdict JSON validé par Pydantic (`STOP` ou `CONTINUE`), borné à cinq
  itérations ;
- un provider de simulation et deux adaptateurs Kimi non interactifs.

Le multi-provider réel, LangGraph et le multi-cascade ne font pas encore partie
de ce jalon.

## Installation de développement

```bash
uv sync --dev
```

## Installation comme commande utilisateur

Sous WSL, la commande peut être installée dans `~/.local/bin/goal` :

```bash
uv tool install --force --editable /mnt/c/Users/eddie/ZCodeProject/goal-cascade-cli
goal --help
```

Le mode éditable garantit que la commande exécute le code du projet visible au
chemin ci-dessus.

## Tests

```bash
uv run pytest -p no:cacheprovider -q
```

## Exemples

```bash
# Test local déterministe
uv run goal run --objective "Auditer un argument" --variant A --provider mock

# Chaque appel ouvre une nouvelle session Kimi CLI non interactive
uv run goal run --objective "Auditer un argument" --variant A \
  --provider kimi-cli --synthesizer-model "provider/modele-small"

# Même contrat avec Kimi Code
uv run goal run --objective "Auditer un argument" --variant A \
  --provider kimi-code --synthesizer-model "provider/modele-small"
```

Le modèle de synthèse peut aussi être fourni par la variable
`GOAL_SYNTHESIZER_MODEL`. Pour un provider Kimi, son absence bloque le run afin
d'éviter la réutilisation silencieuse du modèle principal.

Les coûts des abonnements Kimi ne sont pas exposés par les flux CLI utilisés.
Le programme les affiche donc comme **non mesurés**, jamais comme gratuits.

## Traçabilité permanente

Chaque run est conservé sous `~/.goal/runs/<run_id>/`. La commande affiche ce
chemin dès le démarrage. Le dossier contient notamment :

- `events.jsonl` : événements append-only, horodatés et numérotés ;
- `prompt_<iteration>_<role>.txt` : chaque prompt envoyé ;
- `iteration_<n>.txt` et `synthesis_<n>.json` : chaque résultat brut ;
- `state.json` et `final_output.md` : état et livrable final ;
- `timeline.md` : manifeste humain complet, destiné au RAG ;
- `rag-status.json` : reçu observable de l'indexation et de l'embedding.

Les formes usuelles de mots de passe, jetons, clés API et en-têtes
d'autorisation sont masquées avant persistance. Elles ne doivent jamais être
placées volontairement dans un objectif ou une contrainte.

## RAG PostgreSQL et embeddings ia-general

À la fin de chaque run, `timeline.md` est envoyé de manière ciblée dans la
catégorie PostgreSQL `goal-cascade`. Aucun scan global des credentials n'est
effectué. Les embeddings sont exclusivement demandés à
`ia-general` (`localhost:11434`) avec `bge-m3:latest`, dimension 1024.

```bash
goal rag-status <run_id>
goal rag-sync <run_id>
```

Signification des statuts :

- `pending` : manifeste local créé, synchronisation pas encore tentée ;
- `indexing` : synchronisation en cours ;
- `indexed_pending_embedding` : contenu identique présent dans PostgreSQL,
  mais aucun vecteur n'a encore été validé sur ia-general ;
- `embedded` : chunks 1024D écrits et relecture vectorielle réussie ;
- `failed` : échec avant confirmation de l'indexation PostgreSQL.

Une indisponibilité de `ia-general` reste enregistrée dans `events.jsonl`,
`timeline.md`, `rag-status.json` et PostgreSQL. Elle n'est jamais transformée
en faux succès ; `goal rag-sync <run_id>` reprend la tentative.

## Statut

Cascade unique testée et installée comme commande utilisateur. La traçabilité
locale et l'indexation PostgreSQL sont intégrées. Le multi-provider API,
LangGraph et le multi-cascade ne font pas encore partie de ce jalon. Le statut
`embedded` dépend de la disponibilité réelle de `ia-general`.

## Licence

MIT — voir `LICENSE`.
