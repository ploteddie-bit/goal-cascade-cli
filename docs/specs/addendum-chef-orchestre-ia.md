# Addendum normatif V2 — Chef d'orchestre IA

| Champ | Valeur |
|---|---|
| Statut | Contrat V2 normatif |
| Portée | Couche de pilotage supérieure |
| Relation | Complète `goal-cascade-implementation-v2.md` |

## Séparation obligatoire

Le **chef d'orchestre est une IA persistante**. L'**orchestrateur est
déterministe**. Ces deux responsabilités ne sont ni synonymes ni
interchangeables.

```text
Humain
  ↕
Chef d'orchestre IA persistant
  ↓ commande et supervise
Orchestrateur déterministe
  ↓ exécute les règles
Cascades / agents / providers / outils
  ↓ produisent
Preuves et événements
  ↺ remontent au chef d'orchestre IA
```

## Chef d'orchestre IA

Le chef d'orchestre :

- maintient une session durable avec l'humain ;
- conduit la découverte et consolide le `ProjectBrief` ;
- choisit entre cascade simple et multi-cascade selon le contrat ;
- commande l'orchestrateur déterministe sans modifier directement son état ;
- observe les événements, résultats, erreurs et preuves ;
- analyse les incidents et sélectionne une reprise autorisée ;
- sollicite une validation humaine pour toute action sensible, destructive ou
  extérieure au périmètre accordé ;
- poursuit jusqu'à un résultat vérifié ou un blocage humain explicite.

## Orchestrateur déterministe

L'orchestrateur :

- exécute le graphe, les transitions et les checkpoints ;
- applique les frozen specs, contrats d'interface et validations CI/CD ;
- impose les budgets, limites, retries bornés et critères STOP/CONTINUE ;
- produit les reçus et traces vérifiables ;
- interdit au chef d'orchestre et aux agents de contourner les garde-fous.

## Critères d'acceptation

La couche chef d'orchestre ne peut être déclarée fonctionnelle que si :

1. une session interrompue reprend depuis son état durable sans demander à
   l'utilisateur de reconstituer le contexte ;
2. une erreur récupérable est observée, classifiée et traitée selon une
   stratégie autorisée ;
3. une action nécessitant l'humain suspend réellement l'exécution avant toute
   mutation ;
4. chaque décision du chef d'orchestre référence les événements et preuves qui
   la justifient ;
5. aucun succès n'est déclaré avant satisfaction des gates déterministes V2 ;
6. un test de production couvre au minimum une cascade complète, une panne
   récupérable, une reprise et un blocage humain.
