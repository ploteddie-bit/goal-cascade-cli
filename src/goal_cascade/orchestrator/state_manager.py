"""State Manager — persistance de l'etat en JSON.

Phase 1 : stockage simple dans ~/.goal/runs/<run_id>/.
Phase 4 : migration vers SQLite avec LangGraph.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..schemas.models import CascadeState

GOAL_DIR = Path(os.environ.get("GOAL_HOME", Path.home() / ".goal")).expanduser()
RUNS_DIR = GOAL_DIR / "runs"


def get_run_dir(run_id: str) -> Path:
    """Retourne le dossier d'un run."""
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
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
