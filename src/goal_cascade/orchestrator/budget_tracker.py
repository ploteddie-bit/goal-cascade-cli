"""Kill switch budgétaire (spec V2 §9.2).

Vérifie le budget AVANT chaque itération. Si hard_stop=true et le budget
est dépassé, lève BudgetExceeded pour interrompre proprement le run.
L'état est sauvegardé (checkpoint) pour permettre goal resume.

Fusion des deux versions :
- Structure Eddie : BudgetExceeded enrichi, check_budget, _compute_daily_cost,
  properties, _warned_runs
- Utilitaires existants : record, projected_monthly, explain
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

try:
    import structlog

    logger: Any = structlog.get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

from ..config import BudgetConfig


class BudgetExceeded(Exception):
    """Le budget est atteint. Le run est interrompu proprement.

    L'état est sauvegardé (checkpoint), l'utilisateur peut reprendre
    après ajustement du budget via goal resume.
    """

    def __init__(
        self,
        run_id: str,
        accumulated: float,
        limit: float,
        scope: str,
    ):
        self.run_id = run_id
        self.accumulated = accumulated
        self.limit = limit
        self.scope = scope  # "per_run" ou "per_day"
        super().__init__(
            f"Budget dépassé ({scope}): ${accumulated:.3f} / ${limit:.3f} "
            f"(run {run_id})"
        )


class BudgetTracker:
    """Kill switch budgétaire avec alerte et hard stop.

    Usage dans CascadeExecutor._run_loop :
        tracker.check_budget(state.run_id, state.accumulated_cost)
    """

    def __init__(
        self,
        config: BudgetConfig,
        runs_dir: Path | None = None,
        daily_total_path: Path | None = None,
    ):
        self._config = config
        self._runs_dir = runs_dir or Path.home() / ".goal" / "runs"
        self._daily_total_path = daily_total_path
        self._daily_total: float = self._load_daily_total()
        self._warned_runs: set[str] = set()

    @property
    def config(self) -> BudgetConfig:
        return self._config

    @property
    def daily_total(self) -> float:
        return self._daily_total

    @property
    def max_per_run(self) -> float:
        return self._config.max_per_run_usd

    @property
    def max_per_day(self) -> float:
        return self._config.max_per_day_usd

    @property
    def warn_threshold(self) -> float:
        return self._config.warn_at_percent / 100.0

    @property
    def hard_stop(self) -> bool:
        return self._config.hard_stop

    # ── Check principal (lève l'exception) ──────────────────────

    def check_budget(self, run_id: str, accumulated_cost: float) -> None:
        """Vérifie le budget avant une itération.

        Args:
            run_id: Identifiant du run en cours.
            accumulated_cost: Coût cumulé du run jusqu'à présent.

        Raises:
            BudgetExceeded: Si hard_stop=True et budget dépassé.
        """
        # 1. Check per-run
        if accumulated_cost >= self._config.max_per_run_usd:
            logger.error(
                "budget_exceeded run=%s accumulated=%.3f limit=%.3f scope=per_run",
                run_id,
                accumulated_cost,
                self._config.max_per_run_usd,
            )
            if self._config.hard_stop:
                raise BudgetExceeded(
                    run_id,
                    accumulated_cost,
                    self._config.max_per_run_usd,
                    "per_run",
                )

        # 2. Alert per-run (une seule fois par run)
        warn_amount = self._config.max_per_run_usd * self.warn_threshold
        if accumulated_cost >= warn_amount and run_id not in self._warned_runs:
            pct = (accumulated_cost / self._config.max_per_run_usd) * 100
            logger.warning(
                "budget_warning run=%s accumulated=%.3f limit=%.3f percent=%.0f%%",
                run_id,
                accumulated_cost,
                self._config.max_per_run_usd,
                pct,
            )
            self._warned_runs.add(run_id)

        # 3. Check per-day (cumul quotidien via daily_total_path ou events.jsonl + coût du run)
        daily_cost = max(self._daily_total, self._compute_daily_cost()) + accumulated_cost
        if daily_cost >= self._config.max_per_day_usd:
            logger.error(
                "daily_budget_exceeded daily=%.3f limit=%.3f",
                daily_cost,
                self._config.max_per_day_usd,
            )
            if self._config.hard_stop:
                raise BudgetExceeded(
                    run_id,
                    daily_cost,
                    self._config.max_per_day_usd,
                    "per_day",
                )

    # ── Vérification silencieuse ────────────────────────────────

    def is_exceeded(self, run_id: str, accumulated_cost: float) -> bool:
        """Vérifie silencieusement si le budget est dépassé (sans lever)."""
        try:
            self.check_budget(run_id, accumulated_cost)
            return False
        except BudgetExceeded:
            return True

    def is_warning(self, current_cost: float) -> bool:
        """Vrai si on a atteint le seuil d'alerte sur le run courant."""
        if self._config.max_per_run_usd <= 0:
            return False
        pct = (current_cost / self._config.max_per_run_usd) * 100
        return pct >= self._config.warn_at_percent

    # ── Enregistrement des coûts ────────────────────────────────

    def record(self, cost: float) -> None:
        """Incrémente le cumul quotidien et persiste sur disque.

        En cas d'échec d'écriture (FS readonly, permissions...), on log
        en silence et on continue en mémoire seule.
        """
        self._daily_total += cost
        self._save_daily_total()

    def projected_monthly(self, current_cost: float) -> float:
        """Projection mensuelle basée sur le coût du run et la cadence supposée.

        Hypothèse : on fait ``runs_per_day_projection`` runs par jour,
        chaque run coûtant ``current_cost``.
        """
        return current_cost * 30 * self._config.runs_per_day_projection

    def explain(self, current_cost: float) -> str:
        """Message humain expliquant l'état du budget (debug, logs)."""
        return (
            f"coût={current_cost:.4f}$ / max_run={self._config.max_per_run_usd:.2f}$ "
            f"({100 * current_cost / self._config.max_per_run_usd:.0f}%) | "
            f"cumul_jour={self._daily_total:.4f}$ / max_jour={self._config.max_per_day_usd:.2f}$ "
            f"({100 * (self._daily_total + current_cost) / self._config.max_per_day_usd:.0f}%)"
        )

    # ── Calcul du coût quotidien via events.jsonl ───────────────

    def _compute_daily_cost(self) -> float:
        """Calcule le coût total de tous les runs d'aujourd'hui.

        Lit les events.jsonl de chaque run créé aujourd'hui et somme
        les cost_usd des événements provider_call_completed.
        """
        today = date.today().isoformat()
        total = 0.0

        if not self._runs_dir.exists():
            return 0.0

        for run_dir in self._runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            events_file = run_dir / "events.jsonl"
            if not events_file.exists():
                continue

            # Vérifier si le run a été créé aujourd'hui
            try:
                first_line = events_file.read_text(encoding="utf-8").split("\n")[0]
                if today not in first_line:
                    continue
            except (OSError, IndexError):
                continue

            # Sommer les coûts
            try:
                for line in (
                    events_file.read_text(encoding="utf-8").strip().split("\n")
                ):
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if event.get("event") == "provider_call_completed":
                        total += event.get("cost_usd", 0.0)
            except (json.JSONDecodeError, OSError):
                continue

        return total

    # ── Persistance quotidienne (fallback si events.jsonl absent) ─

    def _load_daily_total(self) -> float:
        """Charge le cumul du jour depuis le fichier JSON.

        Si le fichier date d'un autre jour, on recommence à zéro.
        En cas d'erreur de lecture, on retourne 0.0 (dégradation douce).
        """
        if self._daily_total_path is None:
            return 0.0
        try:
            if not self._daily_total_path.exists():
                return 0.0
            data = json.loads(self._daily_total_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return 0.0
            if data.get("date") != date.today().isoformat():
                return 0.0
            total = data.get("total", 0.0)
            return float(total) if total is not None else 0.0
        except (OSError, ValueError, json.JSONDecodeError):
            return 0.0

    def _save_daily_total(self) -> None:
        """Persiste le cumul quotidien. Échec silencieux toléré."""
        if self._daily_total_path is None:
            return
        try:
            self._daily_total_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "date": date.today().isoformat(),
                "total": self._daily_total,
            }
            self._daily_total_path.write_text(
                json.dumps(payload, indent=2),
                encoding="utf-8",
            )
        except OSError:
            # FS readonly ou permissions : on accepte la dégradation en mémoire seule.
            pass

    def reset_warnings(self) -> None:
        """Réinitialise les alertes (pour les tests)."""
        self._warned_runs.clear()
