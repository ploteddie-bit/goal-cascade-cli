"""Mock Provider — simule des reponses LLM qui reagissent VRAIMENT au contenu.

La difference avec un mock naif :
- L'iteration 2 (Critique) lit reellement le draft de l'iteration 1
- L'iteration 3 (Adversaire) lit reellement les corrections de l'iteration 2
- L'iteration 4 (Arbitre) lit la synthese filtree et les artefacts

Chaque transformation est VISIBLE dans le output. On voit la cascade travailler.
"""

from __future__ import annotations

import hashlib
import json
import re
import time

from .base import BaseProvider, LLMResponse


class MockProvider(BaseProvider):
    """Provider mock qui transforme reellement le contenu a chaque etape."""

    @property
    def name(self) -> str:
        return "mock"

    def call(self, prompt: str, role: str, tier: str = "medium") -> LLMResponse:
        start = time.time()
        time.sleep(0.15)

        generators = {
            "producer": self._producer_response,
            "synthesizer": self._synthesizer_response,
            "critic": self._critic_response,
            "adversary": self._adversary_response,
            "arbiter": self._arbiter_response,
        }

        generator = generators.get(role, self._generic_response)
        text = generator(prompt)

        latency = int((time.time() - start) * 1000)

        return LLMResponse(
            text=text,
            provider="mock",
            model=f"mock-{tier}",
            input_tokens=len(prompt) // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
            latency_ms=latency,
            token_count_estimated=True,
        )

    # --- Extraction ---

    def _extract_objective(self, prompt: str) -> str:
        """Extrait l'objectif du prompt."""
        for marker in [
            "OBJECTIF INITIAL :\n",
            "OBJECTIF A GARDER EN TETE :\n",
            "OBJECTIF :\n",
            "OBJECTIF:\n",
            "Objectif :\n",
        ]:
            if marker in prompt:
                start = prompt.index(marker) + len(marker)
                # Prendre la ligne suivante comme objectif
                end = prompt.find("\n", start)
                if end == -1:
                    end = start + 120
                return prompt[start:end].strip()
        return "[objectif non trouve]"

    def _extract_previous_output(self, prompt: str) -> str:
        """Extrait le contenu precedent (draft ou synthese) du prompt."""
        for marker in [
            "DRAFT A VERIFIER :\n",
            "TRAVAIL ACTUEL",
            "TRAVAIL CUMULE",
        ]:
            if marker in prompt:
                start = prompt.index(marker)
                return prompt[start : start + 1200]
        # Fallback : si aucun marker, prendre la seconde moitie du prompt
        if len(prompt) > 200:
            return prompt[len(prompt) // 2 :]
        return prompt

    # --- Compteurs pour rendre la transformation visible ---

    def _count_claims(self, text: str) -> list[str]:
        """Extrait les affirmations/points du texte."""
        claims = []
        for line in text.split("\n"):
            line = line.strip()
            # Lignes numerotees ou avec puces
            if (re.match(r"^[\d\-\*\+]\s+", line) or "[" in line) and len(line) > 10:
                claims.append(line)
        return claims[:8]  # max 8

    def _generate_id(self, text: str) -> str:
        """Genere un hash court pour montrer que l'input a change."""
        return hashlib.md5(text.encode()).hexdigest()[:8]

    # --- Les 4 roles : chacun transforme reellement ---

    def _synthesizer_response(self, prompt: str) -> str:
        """Produit le contrat JSON attendu entre deux itérations."""
        objective = self._extract_objective(prompt)
        return json.dumps(
            {
                "objective": objective,
                "key_decisions": [
                    "Conserver l'objectif invariant",
                    "Intégrer les corrections vérifiées",
                    "Préserver les artefacts techniques intacts",
                ],
                "uncertainties": ["Validation finale encore requise"],
                "next_instruction": "Exécuter strictement le rôle suivant",
            },
            ensure_ascii=False,
        )

    def _producer_response(self, prompt: str) -> str:
        """Iteration 1 : produit un draft a partir de l'objectif seul."""
        objective = self._extract_objective(prompt)

        # Le producer reflechit a l'objectif et structure une reponse
        return f"""DRAFT INITIAL — Producteur (mock-small)
=====================================
[input hash: {self._generate_id(objective)}]

Objectif traite : {objective}

STRUCTURE PROPOSEE :
1. Introduction : pourquoi le sujet importe
2. Arguments principaux (3 points)
3. Exemple concret
4. Conclusion et appel a l'action

ARGUMENT 1 : Le sujet est sous-estime par la majorite des praticiens. [confiance: MOYENNE]
ARGUMENT 2 : Les donnees recentes (2024) montrent un changement de paradigme. [confiance: HAUTE]
ARGUMENT 3 : Une methode structuree donne de meilleurs resultats que l'improvisation. [confiance: FAIBLE]

EXEMPLE : Cas d'usage en production — resultats observes sur 3 mois.

SOURCES CITEES :
- Etude de reference (2024) [MOYENNE — date exacte a confirmer]
- Rapport technique officiel [HAUTE]
- Blog post d'un expert [FAIBLE — opinion non verifiee]

NOTE : Ce draft est volontairement imparfait. Il contient 1 confiance FAIBLE
et 1 source d'opinion. La critique doit les identifier.
"""

    def _critic_response(self, prompt: str) -> str:
        """Iteration 2 : lit le draft et verifie les sources/confiances."""
        objective = self._extract_objective(prompt)
        previous = self._extract_previous_output(prompt)
        prev_hash = self._generate_id(previous)

        # Le critique CHERCHE les confiances FAIBLES et sources d'opinion
        weak_claims = []
        for line in previous.split("\n"):
            if "FAIBLE" in line or "faible" in line:
                weak_claims.append(line.strip())

        opinion_sources = []
        for line in previous.split("\n"):
            if "opinion" in line.lower() or "blog" in line.lower():
                opinion_sources.append(line.strip())

        report = f"""RAPPORT DE VERIFICATION — Critique (mock-medium)
==================================================
[input hash: {prev_hash} — lit le draft precedent]
[objectif : {objective[:80]}]

VERIFICATION DES CONFIANCES :
  [OK]   Argument 2 (HAUTE) — source verifiable, date plausible
  [!]    Argument 1 (MOYENNE) — source a confirmer
  [X]    Argument 3 (FAIBLE) — manque de preuves
"""

        if weak_claims:
            report += f"""
CONFIANCES FAIBLES DETECTEES ({len(weak_claims)}) :
"""
            for i, claim in enumerate(weak_claims, 1):
                report += f"  {i}. {claim[:100]}\n"

        if opinion_sources:
            report += f"""
SOURCES D'OPINION DETECTEES ({len(opinion_sources)}) :
"""
            for src in opinion_sources:
                report += f"  [!] {src[:100]}\n"

        report += f"""
HALLUCINATIONS POTENTIELLES : {len(weak_claims)} point(s) faible(s) detecte(s)
RECOMMANDATION : Renforcer l'argument 3 ou le retirer.
RESULTAT : {len(weak_claims)} correction(s) necessaire(s) avant validation.
"""
        return report

    def _adversary_response(self, prompt: str) -> str:
        """Iteration 3 : lit les corrections et cherche les angles morts."""
        objective = self._extract_objective(prompt)
        previous = self._extract_previous_output(prompt)
        prev_hash = self._generate_id(previous)

        # L'adversaire compte les sections traitees vs manquantes
        sections_present = sum(
            1 for s in ["introduction", "conclusion", "exemple", "methode"] if s in previous.lower()
        )
        sections_manquantes = [
            s
            for s in ["introduction", "conclusion", "exemple", "methode"]
            if s not in previous.lower()
        ]

        # Compter les arguments
        arg_count = previous.lower().count("argument")

        report = f"""RAPPORT ADVERSARIAL — Adversaire (mock-large)
==============================================
[input hash: {prev_hash} — lit le rapport du critique]
[objectif : {objective[:80]}]

SECTIONS COUVERTES : {sections_present}/4
ARGUMENTS ANALYSES : {arg_count}

ANGLES MORTS (ce qui manque) :
  1. Le public debutant n'est pas adresse
  2. Aucune mention des couts ou contraintes pratiques
  3. Les contre-arguments evidents ne sont pas anticipees
"""

        if sections_manquantes:
            report += f"  4. Sections manquantes : {', '.join(sections_manquantes)}\n"

        report += f"""
BIAIS IMPLICITES :
  1. Postulat que le lecteur connait deja le sujet
  2. Toutes les sources vont dans le meme sens (pas de debat)

CONTRE-ARGUMENTS :
  1. Une approche plus simple pourrait donner des resultats equivalents
  2. Le ROI de la methode n'est pas demontre

RISQUES :
  - Si le contexte reel differe, la methode peut echouer
  - Generalisation non prouvee (3 mois d'exemple, c'est court)

VERDICT DE L'ADVERSAIRE : {len(sections_manquantes) + 3} point(s) faible(s) a adresser.
"""
        return report

    def _arbiter_response(self, prompt: str) -> str:
        """Iteration 4 : arbitre le contexte filtré et rend un verdict JSON."""
        objective = self._extract_objective(prompt)
        previous = prompt
        prev_hash = self._generate_id(previous[:500])

        # L'arbitre verifie le contenu global
        has_conclusion = "conclusion" in previous.lower()
        has_example = "exemple" in previous.lower()
        # Compter les flags de correction dans TOUT le prompt
        corrections_mentioned = previous.count("[X]") + previous.count("[!]")
        adversary_points = previous.count("ANGLES MORTS") + previous.count("CONTRE-ARGUMENT")
        weak_confidence = previous.lower().count("faible")

        # Decision basee sur le contenu reel
        if corrections_mentioned <= 3 and adversary_points <= 2:
            decision = "STOP"
            reason = "Les corrections mineures ne justifient pas une iteration supplementaire."
        else:
            decision = "CONTINUE"
            reason = f"{corrections_mentioned} corrections + {adversary_points} points adverses non resolus."

        report = f"""VERDICT FINAL — Arbitre (mock-xlarge)
=====================================
[input hash: {prev_hash} — lit l'ensemble du travail]
[objectif : {objective[:80]}]

ANALYSE DU CONTENU :
  - Conclusion presente : {"OUI" if has_conclusion else "NON"}
  - Exemple presente : {"OUI" if has_example else "NON"}
  - Corrections identifiees : {corrections_mentioned}
  - Points adverses : {adversary_points}
  - Confiances faibles : {weak_confidence}

EVALUATION DE L'ALIGNEMENT :
  - L'objectif est-il adresse ? OUI
  - Le contenu sert-il l'objectif ? OUI
  - Les sources sont-elles verifiees ? PARTIELLEMENT

VERSION FINALE :
Le livrable integre le draft du producteur, les corrections du critique
({corrections_mentioned} points), et les angles morts de l'adversaire
({adversary_points} elements). La version finale est produite.
"""
        verdict = json.dumps(
            {"decision": decision, "justification": reason},
            ensure_ascii=False,
            indent=2,
        )
        return f"{report}\n```json\n{verdict}\n```"

    def _generic_response(self, prompt: str) -> str:
        objective = self._extract_objective(prompt)
        return f"[Mock response]\nObjectif : {objective}\nHash input : {self._generate_id(prompt)}"
