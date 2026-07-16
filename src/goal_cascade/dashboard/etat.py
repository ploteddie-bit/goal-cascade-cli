"""Helpers de lecture d'état pour le tableau de bord.

Conforme à AGENTS.md (prévention anglais technique) : tous les noms
publics sont en français. Les champs JSON exposés à l'UI portent
des libellés français alignés sur le domaine métier G.O.A.L.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..orchestrator import state_manager
from ..schemas.models import CascadeState

logger = logging.getLogger(__name__)


# ── Mapping variante → noms de templates ──────────────────────────

_PROMPTS_PAR_VARIANTE: dict[str, list[str]] = {
    "A": [
        "iteration_1",
        "iteration_2",
        "iteration_3",
        "iteration_4",
        "synthesis",
    ],
    "B": [
        "technical_iteration_1",
        "technical_iteration_2",
        "technical_iteration_3",
        "technical_iteration_4",
        "synthesis",
    ],
}


def lister_cascades(
    limite: int = 50,
    decalage: int = 0,
    tri: str = "recents",
    statut: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    """Liste paginée et filtrée des cascades disponibles sous RUNS_DIR.

    Args:
        limite: nombre max de résultats (plafonné à 100, plancher à 1).
        decalage: offset pour pagination.
        tri: 'recents' (par défaut) ou 'anciens'.
        statut: filtre exact sur le statut (None = tous).
        q: substring insensible à la casse sur l'objectif (None = tous).

    Returns:
        dict avec clés 'cascades', 'total', 'limite', 'decalage'.
    """
    # Plafonds et planchers
    limite = max(1, min(100, limite))
    decalage = max(0, decalage)

    if not state_manager.RUNS_DIR.exists():
        return {
            "cascades": [], "total": 0,
            "limite": limite, "decalage": decalage,
        }

    cascades = []
    for rep in sorted(state_manager.RUNS_DIR.iterdir(), reverse=True):
        if not rep.is_dir():
            continue
        brut = _lire_etat_brut(rep.name)
        if brut is None:
            continue
        try:
            etat = CascadeState.model_validate(brut)
        except ValidationError as exc:
            logger.warning(
                "Cascade malformée ignorée %s (%d erreurs)",
                rep.name,
                len(exc.errors()),
            )
            continue

        # Filtres (appliqués ici, pas en SQL, on n'a pas de DB)
        if statut is not None and etat.status != statut:
            continue
        if q is not None and q.lower() not in etat.objective.lower():
            continue

        cascades.append(
            {
                "id_cascade": etat.run_id,
                "objectif": etat.objective,
                "statut": etat.status,
                "iteration_courante": etat.current_iteration,
                "nb_max_iterations": etat.max_iterations,
                "cout_cumule": etat.accumulated_cost,
                "verdict": (
                    etat.final_verdict.decision if etat.final_verdict else None
                ),
                "horodatage_demarrage": _horodatage_premier_evenement(rep) or "",
            }
        )

    if tri == "anciens":
        cascades.reverse()

    total = len(cascades)
    page = cascades[decalage : decalage + limite]
    return {
        "cascades": page,
        "total": total,
        "limite": limite,
        "decalage": decalage,
    }


def obtenir_etat_cascade(id_cascade: str) -> dict[str, Any] | None:
    """Détails complets d'une cascade : état, historique, verdict, artefacts, synthèse."""
    brut = _lire_etat_brut(id_cascade)
    if brut is None:
        return None

    try:
        etat = CascadeState.model_validate(brut)
    except ValidationError as exc:
        # Note historique : le code précédent tentait `model_validate(brut, extra="ignore")`
        # en fallback, mais ce kwarg est SILENCIEUSEMENT IGNORÉ en Pydantic v2
        # (pour rendre la validation tolérante il faut ConfigDict(extra="ignore")
        # sur la classe). On logue donc l'échec et on abandonne (retour None)
        # — la cascade sera marquée "malformée" par lister_cascades_malformees().
        logger.warning(
            "Cascade %s invalide (%d erreurs validation), ignorée",
            id_cascade,
            len(exc.errors()),
        )
        return None

    return {
        "id_cascade": etat.run_id,
        "objectif": etat.objective,
        "variante": etat.variant.value,
        "statut": etat.status,
        "iteration_courante": etat.current_iteration,
        "nb_max_iterations": etat.max_iterations,
        "cout_cumule": etat.accumulated_cost,
        "derniere_erreur": etat.last_error,
        "historique": [
            {
                "iteration": h.iteration,
                "role": h.role,
                "fournisseur": h.provider,
                "modele": h.model,
                "jetons_entree": h.input_tokens,
                "jetons_sortie": h.output_tokens,
                "cout_usd": h.cost_usd,
                "latence_ms": h.latency_ms,
                "horodatage_utc": h.timestamp_utc,
                "sortie_brute": h.raw_output,
            }
            for h in etat.history
        ],
        "artefacts": [
            {
                "type_artefact": a.artifact_type,
                "langage": a.language,
                "contenu": a.content,
                "empreinte": a.checksum,
                "iteration_source": a.source_iteration,
            }
            for a in etat.artifacts
        ],
        "derniere_synthese": (
            etat.last_synthesis.model_dump() if etat.last_synthesis else None
        ),
        "verdict_final": (
            etat.final_verdict.model_dump() if etat.final_verdict else None
        ),
        "specification_gelee": (
            etat.frozen_spec.model_dump() if etat.frozen_spec else None
        ),
    }


def _lire_etat_brut(id_cascade: str) -> dict[str, Any] | None:
    """Lit le state.json brut en contournant la validation stricte initiale."""
    chemin = state_manager.get_run_dir(id_cascade, create=False) / "state.json"
    if not chemin.exists():
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def lister_fichiers_cascade(id_cascade: str) -> dict[str, Any]:
    """Liste les fichiers persistés avec tailles et dates ISO 8601."""
    rep = state_manager.get_run_dir(id_cascade, create=False)
    if not rep.exists():
        return {"id_cascade": id_cascade, "fichiers": []}
    fichiers = []
    for chemin in sorted(rep.iterdir()):
        if chemin.is_file():
            stat = chemin.stat()
            fichiers.append(
                {
                    "nom": chemin.name,
                    "chemin": str(chemin),
                    "taille": stat.st_size,
                    "modifie": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                }
            )
    return {"id_cascade": id_cascade, "fichiers": fichiers}


def lire_evenements_depuis(id_cascade: str, depuis_sequence: int = 0) -> list[dict[str, Any]]:
    """Lit les événements du journal depuis la séquence `depuis_sequence` (exclue)."""
    chemin = state_manager.get_run_dir(id_cascade, create=False) / "events.jsonl"
    if not chemin.exists():
        return []
    evenements = []
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            evenement = json.loads(ligne)
        except json.JSONDecodeError:
            continue
        if evenement.get("sequence", 0) > depuis_sequence:
            evenements.append(evenement)
    return evenements


def obtenir_derniere_sequence(id_cascade: str) -> int:
    """Retourne la dernière séquence d'événement (0 si aucun)."""
    chemin = state_manager.get_run_dir(id_cascade, create=False) / "events.jsonl"
    if not chemin.exists():
        return 0
    derniere = 0
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            evenement = json.loads(ligne)
            derniere = max(derniere, evenement.get("sequence", 0))
        except json.JSONDecodeError:
            continue
    return derniere


def obtenir_recu(id_cascade: str) -> dict[str, Any] | None:
    """Charge le reçu de coût (receipt.json)."""
    chemin = state_manager.get_run_dir(id_cascade, create=False) / "receipt.json"
    if not chemin.exists():
        return None
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _horodatage_premier_evenement(rep: Path) -> str | None:
    """Lit le timestamp du tout premier événement du journal."""
    chemin = rep / "events.jsonl"
    if not chemin.exists():
        return None
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if not ligne.strip():
            continue
        try:
            evenement = json.loads(ligne)
            return evenement.get("timestamp_utc")
        except json.JSONDecodeError:
            continue
    return None


def obtenir_prompts_cascade(id_cascade: str, variante: str = "A") -> dict[str, str]:
    """Lit les prompts Jinja2 utilisés pour une cascade donnée.

    Priorité de chargement :
    1. `~/.goal/runs/<id_cascade>/prompts/<role>.j2` (override sauvegardé)
    2. PromptLoader standard (project > user > package)

    Args:
        id_cascade: Identifiant de la cascade.
        variante: "A" (rédactionnel) ou "B" (technique).
    """
    from ..prompts import PromptLoader

    chargeur = PromptLoader()
    roles = _PROMPTS_PAR_VARIANTE.get(variante, _PROMPTS_PAR_VARIANTE["A"])
    prompts = {}
    rep_prompts = state_manager.get_run_dir(id_cascade, create=False) / "prompts"

    for nom in roles:
        # 1. Override sauvegardé pour cette cascade
        chemin_override = rep_prompts / f"{nom}.j2"
        if chemin_override.exists():
            try:
                prompts[nom] = chemin_override.read_text(encoding="utf-8")
                continue
            except OSError:
                pass
        # 2. PromptLoader standard
        try:
            source, _, _ = chargeur.env.loader.get_source(chargeur.env, f"{nom}.j2")  # type: ignore[attr-defined]
            prompts[nom] = source
        except Exception:
            prompts[nom] = ""
    return prompts


def sauvegarder_override_prompt(id_cascade: str, role: str, contenu: str) -> Path:
    """Sauvegarde un override de prompt pour (id_cascade, role).

    Crée `~/.goal/runs/<id_cascade>/prompts/<role>.j2` avec permissions 0o700
    héritées du dossier parent.
    """
    rep = state_manager.get_run_dir(id_cascade)
    rep_prompts = rep / "prompts"
    rep_prompts.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(rep_prompts, 0o700)
    except OSError:
        pass
    chemin = rep_prompts / f"{role}.j2"
    chemin.write_text(contenu, encoding="utf-8")
    try:
        os.chmod(chemin, 0o600)
    except OSError:
        pass
    return chemin


def compter_cascades() -> dict[str, int]:
    """Compteurs de santé du système.

    - runs_total : nombre de dossiers sous RUNS_DIR
    - runs_chargeables : ceux dont le state.json est valide (validation stricte OK)
    - runs_malformes : ceux dont le state.json est corrompu OU échoue la validation
    """
    if not state_manager.RUNS_DIR.exists():
        return {"runs_total": 0, "runs_chargeables": 0, "runs_malformes": 0}
    total = chargeables = malformes = 0
    for rep in state_manager.RUNS_DIR.iterdir():
        if not rep.is_dir():
            continue
        total += 1
        etat_path = rep / "state.json"
        if not etat_path.exists():
            malformes += 1
            continue
        try:
            data = json.loads(etat_path.read_text(encoding="utf-8"))
            # Validation stricte — un run avec champs supplémentaires
            # est compté comme "malformé" (cohérent avec lister_cascades
            # qui l'ignore silencieusement)
            # Note: extra="ignore" kwarg ignoré silencieusement par Pydantic v2
            # (pour rendre la validation tolérante, ajouter ConfigDict(extra="ignore")
            # sur CascadeState OU catch l'erreur). On garde la stricte ici.
            CascadeState.model_validate(data)
            chargeables += 1
        except (ValidationError, json.JSONDecodeError, OSError):
            malformes += 1
    return {"runs_total": total, "runs_chargeables": chargeables, "runs_malformes": malformes}


def lister_cascades_malformees() -> list[dict[str, str]]:
    """Liste les dossiers de run présents mais dont state.json est invalide.

    Utile pour le diagnostic : le dashboard expose cette liste pour
    signaler à l'utilisateur les runs skippés par la validation stricte.
    """
    if not state_manager.RUNS_DIR.exists():
        return []
    malformes = []
    for rep in state_manager.RUNS_DIR.iterdir():
        if not rep.is_dir():
            continue
        etat_path = rep / "state.json"
        if not etat_path.exists():
            malformes.append({
                "id_cascade": rep.name,
                "chemin": str(rep),
                "raison": "state.json absent",
            })
            continue
        try:
            data = json.loads(etat_path.read_text(encoding="utf-8"))
            CascadeState.model_validate(data)  # strict
        except (ValidationError, json.JSONDecodeError, OSError) as exc:
            malformes.append({
                "id_cascade": rep.name,
                "chemin": str(rep),
                "raison": f"state.json invalide ({type(exc).__name__})",
            })
    return malformes
