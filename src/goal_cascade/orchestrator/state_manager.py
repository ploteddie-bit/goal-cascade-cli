"""State Manager — persistance de l'etat en JSON.

Phase 1 : stockage simple dans ~/.goal/runs/<run_id>/.
Phase 4 : migration vers SQLite avec LangGraph.
"""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from ..schemas.models import CascadeState, RunReceipt

GOAL_DIR = Path(os.environ.get("GOAL_HOME", Path.home() / ".goal")).expanduser()
RUNS_DIR = GOAL_DIR / "runs"


PRIVATE_DIR_MODE = 0o700


def ensure_private_dir(path: Path, mode: int = PRIVATE_DIR_MODE) -> Path:
    """Crée un répertoire (et ses parents) avec des permissions restreintes.

    Les traces de run et les données utilisateur ne doivent pas être
    lisibles par les autres utilisateurs du système (E2/E3).
    """
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(mode)
    return path


def _initialize_runs_dir() -> None:
    """Garantit que RUNS_DIR lui-même a les permissions 0o700.

    Sans cela, le umask par défaut peut produire des répertoires en 0o755
    (lisibles par tous) sur les systèmes où mkdir ne respecte pas le mode.
    """
    ensure_private_dir(RUNS_DIR)


_initialize_runs_dir()


def get_run_dir(run_id: str, create: bool = True) -> Path:
    """Retourne le chemin du dossier d'un run.

    Args:
        run_id: identifiant hex du run.
        create: si True (défaut), crée le dossier avec permissions 0o700.
            Si False, retourne le chemin sans créer (utilisé par les routes
            GET du dashboard pour éviter la pollution filesystem via des
            requêtes avec run_id forgés — sécurité anti-DoS/anti-pollution).

    Returns:
        Le chemin du dossier (qu'il existe ou non selon ``create``).
    """
    run_dir = RUNS_DIR / run_id
    if create:
        ensure_private_dir(run_dir)
    return run_dir


def save_state(state: CascadeState) -> Path:
    """Sauvegarde l'etat d'une cascade en JSON."""
    run_dir = get_run_dir(state.run_id)
    state_file = run_dir / "state.json"
    state_file.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state_file


def load_state(run_id: str) -> CascadeState | None:
    """Charge l'etat d'une cascade depuis JSON."""
    state_file = RUNS_DIR / run_id / "state.json"
    if not state_file.exists():
        return None
    data = json.loads(state_file.read_text(encoding="utf-8"))
    return CascadeState(**data)


def save_iteration_output(run_id: str, iteration: int, output: str) -> Path:
    """Sauvegarde la sortie brute d'une iteration dans un fichier consultable.
    (Angle mort identifie : chaque iteration doit etre persistee.)"""
    run_dir = get_run_dir(run_id)
    output_file = run_dir / f"iteration_{iteration}.txt"
    output_file.write_text(output, encoding="utf-8")
    return output_file


def save_prompt_output(run_id: str, iteration: int, role: str, prompt: str) -> Path:
    """Sauvegarde le prompt exact envoyé à un rôle."""
    run_dir = get_run_dir(run_id)
    output_file = run_dir / f"prompt_{iteration}_{role}.txt"
    output_file.write_text(prompt, encoding="utf-8")
    return output_file


def save_synthesis_output(run_id: str, iteration: int, output: str) -> Path:
    """Sauvegarde la réponse brute du synthétiseur après une itération."""
    run_dir = get_run_dir(run_id)
    output_file = run_dir / f"synthesis_{iteration}.json"
    output_file.write_text(output, encoding="utf-8")
    return output_file


def save_final_output(run_id: str, output: str) -> Path:
    """Sauvegarde le livrable final."""
    run_dir = get_run_dir(run_id)
    output_file = run_dir / "final_output.md"
    output_file.write_text(output, encoding="utf-8")
    return output_file


def save_receipt(run_id: str, receipt: RunReceipt) -> Path:
    """Sauvegarde le recu detaille du run (transparence des couts)."""
    run_dir = get_run_dir(run_id)
    output_file = run_dir / "receipt.json"
    output_file.write_text(
        receipt.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return output_file


def list_runs() -> list[dict]:
    """Liste tous les runs connus."""
    if not RUNS_DIR.exists():
        return []
    runs = []
    for run_dir in sorted(RUNS_DIR.iterdir(), reverse=True):
        if run_dir.is_dir():
            state_file = run_dir / "state.json"
            if state_file.exists():
                data = json.loads(state_file.read_text(encoding="utf-8"))
                runs.append(
                    {
                        "run_id": data.get("run_id", run_dir.name),
                        "objective": data.get("objective", "")[:60],
                        "status": data.get("status", "unknown"),
                        "iterations": data.get("current_iteration", 0),
                    }
                )
    return runs
