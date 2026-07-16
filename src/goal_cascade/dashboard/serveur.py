"""Serveur FastAPI pour le tableau de bord de pilotage G.O.A.L. Cascade.

Conforme à AGENTS.md (prévention anglais technique) : identifiants
et messages en français. Les préfixes techniques (_VERIFIER_xxx,
_REQUIRES_xxx) restent en anglais car ils relèvent de conventions
PEP 8 et ne sont pas exposés à l'utilisateur.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __init__ as _pkg_init  # noqa: F401  (assure l'enregistrement du package)
from . import etat as etat_tableau

logger = logging.getLogger(__name__)

# ── Sécurité (helpers — déclarés AVANT l'app pour que FastAPI puisse les résoudre) ──

_REGEX_ID_CASCADE = re.compile(r"^[0-9a-f]{4,16}$")
_REGEX_ROLE = re.compile(r"^[a-z][a-z0-9_\-]{0,63}$")
_TAILLE_MAX_PROMPT_OCTETS = 256 * 1024
_INTERVALLE_SONDAGE_SSE_S = 5.0


def _verifier_id_securise(valeur: str, type_id: str) -> str:
    """Bloque les attaques par path traversal (`../`, `/`, `\\`)."""
    motif = _REGEX_ID_CASCADE if type_id == "id_cascade" else _REGEX_ROLE
    if not motif.match(valeur):
        raise HTTPException(
            status_code=400,
            detail=f"{type_id} invalide : '{valeur}' ne respecte pas le format attendu",
        )
    return valeur


def _verifier_token_tableau_de_bord(
    authorization: str | None = Header(default=None),
) -> None:
    """Vérifie le token bearer (GOAL_DASHBOARD_TOKEN) sur les routes sensibles.

    Si la variable d'env n'est pas définie : auth désactivée (mode dev).
    """
    attendu = os.environ.get("GOAL_DASHBOARD_TOKEN")
    if not attendu:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization Bearer requis")
    fourni = authorization[len("Bearer ") :].strip()
    if fourni != attendu:
        raise HTTPException(status_code=403, detail="Token invalide")


# ── Application ─────────────────────────────────────────────────

# D3 : Auth globale. La dépendance _verifier_token_tableau_de_bord()
# ne déclenche un 401 QUE si GOAL_DASHBOARD_TOKEN est défini dans
# l'environnement. En dev local (token absent), toutes les routes
# restent accessibles. En prod (token présent), TOUTES les routes
# (lecture et écriture) exigent un Bearer valide.
app = FastAPI(
    title="G.O.A.L. Cascade — Tableau de bord",
    description="Pilotage temps réel d'une cascade multi-agents.",
    version="0.1.0",
    dependencies=[Depends(_verifier_token_tableau_de_bord)],
)

_REP_MODELES = Path(__file__).parent / "templates"
_REP_STATIQUE = Path(__file__).parent / "static"


# ── Routes HTML ──────────────────────────────────────────────────


@app.get("/", include_in_schema=False)
async def racine() -> FileResponse:
    """Sert la page HTML principale du tableau de bord."""
    return FileResponse(_REP_MODELES / "index.html")


# ── Routes API ───────────────────────────────────────────────────


@app.get("/api/cascades")
async def lister_cascades(
    limite: int = 50,
    decalage: int = 0,
    tri: str = "recents",
    statut: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Liste paginée et filtrée des cascades connues.

    Query params:
    - limite: nombre max (1-100, défaut 50)
    - decalage: offset pour pagination (défaut 0)
    - tri: 'recents' (défaut) ou 'anciens'
    - statut: filtre exact (ex: 'stopped', 'forced_stop')
    - q: substring insensible à la casse sur l'objectif
    """
    return etat_tableau.lister_cascades(
        limite=limite, decalage=decalage, tri=tri, statut=statut, q=q
    )


@app.get("/api/sante")
async def api_sante() -> dict[str, Any]:
    """Visibilité sur la santé du système.

    Expose les compteurs (total, chargeables, malformes) et la liste
    détaillée des runs skippés par la validation stricte.
    """
    from datetime import UTC, datetime

    return {
        **etat_tableau.compter_cascades(),
        "malformes_detail": etat_tableau.lister_cascades_malformees(),
        "derniere_maj": datetime.now(UTC).isoformat(),
    }


@app.get("/api/cascades/{id_cascade}")
async def obtenir_cascade(id_cascade: str) -> dict[str, Any]:
    """Détails complets d'une cascade."""
    _verifier_id_securise(id_cascade, "id_cascade")
    donnees = etat_tableau.obtenir_etat_cascade(id_cascade)
    if donnees is None:
        raise HTTPException(status_code=404, detail=f"Cascade '{id_cascade}' introuvable")
    return donnees


@app.get("/api/cascades/{id_cascade}/fichiers")
async def lister_fichiers(id_cascade: str) -> dict[str, Any]:
    """Liste des fichiers persistés sous le dossier de la cascade."""
    _verifier_id_securise(id_cascade, "id_cascade")
    return etat_tableau.lister_fichiers_cascade(id_cascade)


@app.get("/api/cascades/{id_cascade}/evenements")
async def lire_evenements(
    id_cascade: str,
    depuis: int = 0,
) -> list[dict[str, Any]]:
    """Événements d'une cascade depuis la séquence `depuis` (lecture one-shot)."""
    _verifier_id_securise(id_cascade, "id_cascade")
    return etat_tableau.lire_evenements_depuis(id_cascade, depuis_sequence=depuis)


@app.get("/api/cascades/{id_cascade}/evenements/flux")
async def flux_evenements(id_cascade: str, request: Request) -> StreamingResponse:
    """SSE : tail temps réel des événements (polling 5s)."""
    _verifier_id_securise(id_cascade, "id_cascade")

    async def generateur():
        derniere_seq = etat_tableau.obtenir_derniere_sequence(id_cascade)
        yield f"event: snapshot\ndata: {json.dumps({'sequence': derniere_seq})}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                evenements = etat_tableau.lire_evenements_depuis(
                    id_cascade, depuis_sequence=derniere_seq
                )
                for ev in evenements:
                    derniere_seq = max(derniere_seq, ev.get("sequence", 0))
                    yield f"event: journal\ndata: {json.dumps(ev)}\n\n"
                yield "event: battement\ndata: {}\n\n"
                await asyncio.sleep(_INTERVALLE_SONDAGE_SSE_S)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        generateur(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/cascades/{id_cascade}/prompts")
async def obtenir_prompts(id_cascade: str) -> dict[str, str]:
    """Prompts Jinja2 (override ou défaut selon la variante)."""
    _verifier_id_securise(id_cascade, "id_cascade")
    donnees = etat_tableau.obtenir_etat_cascade(id_cascade)
    variante = donnees.get("variante", "A") if donnees else "A"
    return etat_tableau.obtenir_prompts_cascade(id_cascade, variante=variante)


@app.put(
    "/api/cascades/{id_cascade}/prompts/{role}",
    dependencies=[Depends(_verifier_token_tableau_de_bord)],
)
async def mettre_a_jour_prompt(
    id_cascade: str,
    role: str,
    charge_utile: dict[str, str],
    request: Request,
) -> dict[str, Any]:
    """Override un prompt. Authentifié si GOAL_DASHBOARD_TOKEN défini.

    Body JSON : `{"contenu": "<nouveau template Jinja2>"}`.
    Tracé dans le journal d'audit de la cascade.
    """
    _verifier_id_securise(id_cascade, "id_cascade")
    _verifier_id_securise(role, "role")

    contenu = charge_utile.get("contenu", "")
    if not contenu.strip():
        raise HTTPException(status_code=400, detail="contenu requis et non vide")
    taille = len(contenu.encode("utf-8"))
    if taille > _TAILLE_MAX_PROMPT_OCTETS:
        raise HTTPException(
            status_code=413,
            detail=f"prompt trop volumineux : {taille} octets (max {_TAILLE_MAX_PROMPT_OCTETS})",
        )

    try:
        chemin = etat_tableau.sauvegarder_override_prompt(id_cascade, role, contenu)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Erreur d'écriture : {exc}") from exc

    client = request.client.host if request.client else "inconnu"
    try:
        from ..audit_journal import AuditJournal

        journal = AuditJournal(id_cascade)
        journal.record_event(
            "prompt_remplace_sauvegarde",
            role=role,
            chemin=str(chemin),
            octets=taille,
            client=client,
        )
        journal.refresh_timeline()
    except Exception as exc:
        logger.warning("journal_audit_indispo cascade=%s exc=%s", id_cascade, exc)

    return {
        "id_cascade": id_cascade,
        "role": role,
        "chemin": str(chemin),
        "octets": taille,
    }


@app.get("/api/cascades/{id_cascade}/recu")
async def obtenir_recu(id_cascade: str) -> dict[str, Any]:
    """Reçu détaillé (transparence coûts)."""
    _verifier_id_securise(id_cascade, "id_cascade")
    recu = etat_tableau.obtenir_recu(id_cascade)
    if recu is None:
        raise HTTPException(status_code=404, detail="Reçu absent pour cette cascade")
    return recu


# ── Assets statiques ────────────────────────────────────────────

if _REP_STATIQUE.exists():
    app.mount("/statique", StaticFiles(directory=str(_REP_STATIQUE)), name="statique")


# ── Lancement direct ────────────────────────────────────────────


def lancer_serveur(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    """Lance uvicorn pour servir le tableau de bord."""
    import uvicorn

    if host not in ("127.0.0.1", "localhost") and not os.environ.get(
        "GOAL_DASHBOARD_TOKEN"
    ):
        logger.warning(
            "Tableau de bord exposé sur %s sans GOAL_DASHBOARD_TOKEN. "
            "Définir GOAL_DASHBOARD_TOKEN pour activer l'auth Bearer.",
            host,
        )

    uvicorn.run(
        "goal_cascade.dashboard.serveur:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
