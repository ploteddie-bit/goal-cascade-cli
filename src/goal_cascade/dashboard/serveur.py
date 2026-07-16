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
    """SSE : tail temps réel des événements (détection par mtime, pas de polling fixe).

    Surveille events.jsonl via ``os.stat()`` (mtime + taille).
    Délai adaptatif : 0.3s quand le fichier change, jusqu'à 5s
    quand il est stable. Zéro dépendance externe.
    """
    _verifier_id_securise(id_cascade, "id_cascade")

    async def generateur():
        derniere_seq = etat_tableau.obtenir_derniere_sequence(id_cascade)
        yield f"event: snapshot\ndata: {json.dumps({'sequence': derniere_seq})}\n\n"
        chemin_fichier = (
            etat_tableau.state_manager.get_run_dir(id_cascade, create=False)
            / "events.jsonl"
        )
        etat_fichier = _EtatFichier(chemin_fichier)
        try:
            while True:
                if await request.is_disconnected():
                    break

                # Attendre la prochaine modification (mtime ou taille)
                await etat_fichier.attendre_modification()

                evenements = etat_tableau.lire_evenements_depuis(
                    id_cascade, depuis_sequence=derniere_seq
                )
                for ev in evenements:
                    derniere_seq = max(derniere_seq, ev.get("sequence", 0))
                    yield f"event: journal\ndata: {json.dumps(ev)}\n\n"

                yield "event: batement\ndata: {}\n\n"
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


class _EtatFichier:
    """Surveille un fichier via os.stat (mtime + taille) avec délai adaptatif.

    Pas de dépendance externe (stdlib uniquement). Détecte les
    modifications en comparant mtime et taille entre deux lectures.
    Délai adaptatif : rapide (0.3s) quand le fichier change,
    lent (5s) quand il est stable.
    """

    _DELAI_RAPIDE = 0.3
    _DELAI_LENT = 5.0
    _SEUIL_STABLE = 5  # nombre de checks sans changement avant passage lent

    def __init__(self, chemin: Path) -> None:
        self._chemin = chemin
        self._dernier_mtime = 0.0
        self._derniere_taille = 0
        self._compteur_stable = 0

    async def attendre_modification(self) -> None:
        """Attend que le fichier soit modifié (mtime ou taille change).

        Délai adaptatif : 0.3s si changement récent, 5s si stable.
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._boucle_attente)

    def _boucle_attente(self) -> None:
        """Boucle bloquante (exécutée dans un thread) qui surveille le fichier."""
        import time as _time

        while True:
            try:
                stat = os.stat(self._chemin)
                mtime = stat.st_mtime
                taille = stat.st_size
            except (OSError, FileNotFoundError):
                mtime, taille = 0.0, 0

            if mtime != self._dernier_mtime or taille != self._derniere_taille:
                self._dernier_mtime = mtime
                self._derniere_taille = taille
                self._compteur_stable = 0
                return  # fichier modifié → retour immédiat

            # Fichier inchangé → délai adaptatif
            self._compteur_stable = min(self._compteur_stable + 1, 20)
            delai = (
                self._DELAI_RAPIDE
                if self._compteur_stable < self._SEUIL_STABLE
                else self._DELAI_LENT
            )
            _time.sleep(delai)


@app.get("/api/cascades/{id_cascade}/prompts")
async def obtenir_prompts(id_cascade: str) -> dict[str, str]:
    """Prompts Jinja2 (override ou défaut selon la variante)."""
    _verifier_id_securise(id_cascade, "id_cascade")
    donnees = etat_tableau.obtenir_etat_cascade(id_cascade)
    variante = donnees.get("variante", "A") if donnees else "A"
    return etat_tableau.obtenir_prompts_cascade(id_cascade, variante=variante)


# ── Éditeur de fichiers (run files) ─────────────────────────────

# Mapping type → chemin relatif (paramètres de l'URL)
def _resolve_run_file_path(
    id_cascade: str,
    type_fichier: str,
    role: str | None = None,
    iteration: int | None = None,
) -> Path:
    """Résout un chemin vers un fichier de run, avec validation stricte.

    Paths supportés :
    - state         → state.json
    - evenements    → events.jsonl
    - iterations/N  → iteration_N.txt
    - syntheses/N   → synthesis_N.json
    - prompts/{role}/N → prompt_N_{role}.txt
    """
    _verifier_id_securise(id_cascade, "id_cascade")

    if type_fichier == "state":
        chemin = "state.json"
    elif type_fichier == "evenements":
        chemin = "events.jsonl"
    elif type_fichier == "iterations":
        if iteration is None or iteration < 1 or iteration > 5:
            # Fichier n'existe pas → 404 (le path /iteration_N.txt n'existe pas)
            raise HTTPException(
                status_code=404,
                detail=f"iteration {iteration} hors range (1-5) — fichier non trouvé",
            )
        chemin = f"iteration_{iteration}.txt"
    elif type_fichier == "syntheses":
        if iteration is None or iteration < 1 or iteration > 5:
            raise HTTPException(
                status_code=404,
                detail=f"iteration {iteration} hors range (1-5) — fichier non trouvé",
            )
        chemin = f"synthesis_{iteration}.json"
    elif type_fichier == "prompts":
        if not role:
            raise HTTPException(
                status_code=400, detail="role requis pour type=prompts"
            )
        if iteration is None or iteration < 1 or iteration > 5:
            raise HTTPException(
                status_code=404,
                detail=f"iteration {iteration} hors range (1-5) — fichier non trouvé",
            )
        # role a déjà été validé comme chemin hex (via _verifier_id_securise
        # sur le path resolver) — mais ici on a un rôle textuel comme
        # "producer" qui n'est PAS un id hex. Validation séparée.
        if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", role):
            raise HTTPException(
                status_code=400,
                detail=f"role invalide : {role!r}",
            )
        chemin = f"prompt_{iteration}_{role}.txt"
    else:
        raise HTTPException(
            status_code=400,
            detail=f"type inconnu: {type_fichier!r} (attendu: state|evenements|iterations|syntheses|prompts)",
        )

    return (
        etat_tableau.state_manager.get_run_dir(id_cascade, create=False)
        / chemin
    )


def _detect_mime_type(chemin: Path) -> str:
    """Devine le type MIME selon l'extension."""
    if chemin.suffix == ".json":
        return "application/json"
    if chemin.suffix == ".jsonl":
        return "application/x-ndjson"
    if chemin.suffix == ".md":
        return "text/markdown"
    return "text/plain"


@app.get("/api/cascades/{id_cascade}/fichier/{type_fichier}/{role}/{iteration}")
async def lire_fichier_prompt(
    id_cascade: str, type_fichier: str, role: str, iteration: int
) -> dict[str, Any]:
    """Lit un prompt (type=prompts, role, iteration)."""
    chemin = _resolve_run_file_path(
        id_cascade, type_fichier, role=role, iteration=iteration
    )
    if not chemin.exists():
        raise HTTPException(
            status_code=404, detail=f"Fichier non trouvé : {chemin.name}"
        )
    contenu = chemin.read_text(encoding="utf-8")
    return {
        "nom": chemin.name,
        "chemin": str(chemin),
        "contenu": contenu,
        "type_mime": _detect_mime_type(chemin),
        "taille": len(contenu),
    }


@app.get("/api/cascades/{id_cascade}/fichier/{type_fichier}/{iteration}")
async def lire_fichier_indexe(
    id_cascade: str, type_fichier: str, iteration: int
) -> dict[str, Any]:
    """Lit un fichier indexé (iterations/N ou syntheses/N)."""
    chemin = _resolve_run_file_path(
        id_cascade, type_fichier, iteration=iteration
    )
    if not chemin.exists():
        raise HTTPException(
            status_code=404, detail=f"Fichier non trouvé : {chemin.name}"
        )
    contenu = chemin.read_text(encoding="utf-8")
    # Pour les JSON, on parse pour retourner un objet (UI plus pratique)
    if chemin.suffix == ".json":
        import json as _json
        try:
            return {
                "nom": chemin.name,
                "chemin": str(chemin),
                "contenu": _json.loads(contenu),
                "type_mime": _detect_mime_type(chemin),
                "taille": len(contenu),
            }
        except _json.JSONDecodeError:
            pass
    return {
        "nom": chemin.name,
        "chemin": str(chemin),
        "contenu": contenu,
        "type_mime": _detect_mime_type(chemin),
        "taille": len(contenu),
    }


@app.get("/api/cascades/{id_cascade}/fichier/{type_fichier}")
async def lire_fichier_simple(
    id_cascade: str, type_fichier: str
) -> dict[str, Any]:
    """Lit un fichier simple (state ou evenements)."""
    chemin = _resolve_run_file_path(id_cascade, type_fichier)
    if not chemin.exists():
        raise HTTPException(
            status_code=404, detail=f"Fichier non trouvé : {chemin.name}"
        )
    contenu = chemin.read_text(encoding="utf-8")
    # state.json est parsé en dict pour l'UI
    if chemin.suffix == ".json":
        import json as _json
        try:
            return {
                "nom": chemin.name,
                "chemin": str(chemin),
                "contenu": _json.loads(contenu),
                "type_mime": _detect_mime_type(chemin),
                "taille": len(contenu),
            }
        except _json.JSONDecodeError:
            pass
    return {
        "nom": chemin.name,
        "chemin": str(chemin),
        "contenu": contenu,
        "type_mime": _detect_mime_type(chemin),
        "taille": len(contenu),
    }


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
