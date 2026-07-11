## TEMPS 1 — ÉVALUATION DE L'ALIGNEMENT

**Objectif initial :** checklist concise de 7 critères, avec colonne de profondeur, pour valider une modification logicielle avant livraison.

Vérification :

- **Couverture des 7 domaines :** Tests, Revue, Interfaces, Erreurs, Sécurité, Performance, Documentation — tous présents. OK.
- **Dérive hors-sujet :** aucune. Chaque décision documentée ramène au périmètre (PR unitaire / changement fonctionnel). OK.
- **Objections de l'adversaire traitées :**
  - Performance ajoutée en 7e domaine niveau [HAUT] — OK.
  - Documentation passée à [MOYEN] non bloquant avec mention obligatoire — OK.
  - Colonne « profondeur attendue » ajoutée pour contrer la coche mécanique — OK.
  - Périmètre d'usage explicitement borné — OK.
  - Processus de révision intégré — OK.
- **Sources vérifiées :** OWASP Top 10 (référence standard sécurité web, validée), principes SRE (Google, domaine public), Twelve-Factor App (Heroku, domaine public). Les trois sont des références stables et largement acceptées. OK.

Aucun angle mort documenté non résolu. Passage à la production finale.

---

## TEMPS 2 — PRODUCTION FINALE

# Checklist de validation avant livraison

> **Usage :** PR unitaires et changements fonctionnels. Les refactoring transversaux, migrations de données et changements d'infrastructure nécessitent une extension séparée.
>
> **Révision :** relire cette checklist tous les 6 mois ou après tout incident majeur de livraison.

| # | Domaine | Critère de profondeur attendue | Niveau | Référence | OK/KO |
|---|---------|-------------------------------|--------|-----------|-------|
| 1 | **Tests** | Couverture ≥ 80 % sur le code touché ; tous les tests existants passent ; au moins 1 test couvre le cas nominal et 1 test couvre un cas limite du changement | [HAUT] | — | ☐ |
| 2 | **Revue de code** | Au moins 1 approbation d'un·e reviewer qualifié·e (connaissance du module) ; 0 commentaire non résolu ; les choix d'architecture contestés ont reçu une réponse explicite | [HAUT] | — | ☐ |
| 3 | **Interfaces & contrats** | Compatibilité ascendante vérifiée (API, schéma BDD, format de message) ; consommateurs directs identifiés et notifiés si rupture ; version bump si contrat public | [HAUT] | — | ☐ |
| 4 | **Gestion des erreurs** | Les chemins d'échec sont testés ; les erreurs sont loguées avec contexte exploitable (quoi, où, quoi faire) ; aucune erreur silencieusement avalée | [HAUT] | — | ☐ |
| 5 | **Sécurité** | Pas de secret en clair dans le diff ; entrées utilisateur validées/sanitisées ; vérification OWASP Top 10 si surface web ; contrôles d'autorisation cohérents avec le périmètre du changement | [HAUT] | OWASP Top 10 | ☐ |
| 6 | **Performance & scalabilité** | Aucune régression mesurée sur les chemins critiques impactés ; usage mémoire/CPU borné et vérifié pour les volumes de production ; si le changement touche un hot path, un test de charge ou une estimation de charge est fourni | [HAUT] | Principes SRE | ☐ |
| 7 | **Documentation** | Changelog ou message de commit à jour ; documentation API synchronisée si contrat modifié ; commentaires inline ajoutés si logique non évidente. **Si omis** → mentionner la raison dans la PR | [MOYEN] | Twelve-Factor App | ☐ |

**Lecture des niveaux :**
- **[HAUT]** = bloquant. La PR ne peut pas être mergée sans OK sur ce critère.
- **[MOYEN]** = non bloquant, mais toute omission doit être justifiée dans la description de la PR. Une justification vide équivaut à un KO.

---

## TEMPS 3 — VERDICT

VERDICT : STOP
JUSTIFICATION : Les 7 domaines sont couverts, les 5 objections de l'adversaire sont intégrées, les sources sont vérifiées, et le livrable final est opérationnel tel que produit ci-dessus.