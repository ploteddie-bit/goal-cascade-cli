"""Tableau de bord de pilotage G.O.A.L. Cascade — FastAPI + SSE.

Expose l'état d'une cascade en cours, les événements temps réel
via Server-Sent Events, et permet l'édition des prompts par rôle.

Architecture :
    GET  /                                    → Tableau de bord HTML
    GET  /api/cascades                        → Liste des cascades
    GET  /api/cascades/{id_cascade}           → Détails d'une cascade
    GET  /api/cascades/{id_cascade}/evenements → SSE : tail journal
    GET  /api/cascades/{id_cascade}/prompts   → Prompts Jinja2 par rôle
    PUT  /api/cascades/{id_cascade}/prompts/{role} → Override d'un prompt

Lancement : `goal tableau-de-bord --port 8080`.
"""

from __future__ import annotations

from .serveur import app, lancer_serveur

__all__ = ["app", "lancer_serveur"]
