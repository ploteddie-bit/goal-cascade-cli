"""Budget tracker et kill switch budgetaire.

Section 9 du plan d'implementation v2 (transparence radicale des couts).
Le tracker :
- empeche un run de depasser ``max_per_run_usd`` (kill switch dur)
- empeche plusieurs runs d'epuiser ``max_per_day_usd`` (cumul quotidien)
- previent quand on atteint ``warn_at_percent`` du budget run
- expose ``projected_monthly`` pour anticiper les couts a l'echelle

Origine du code : section 9 du plan ``goal-cascade-implementation.md``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field


class BudgetConfig(BaseModel):
    """Configuration du budget et du kill switch."""

    max_per_run_usd: float = Field(default=0.50, gt=0)
    max_per_day_usd: float = Field(default=10.00, gt=0)
    warn_at_percent: int = Field(default=80, ge=0, le=100)
    hard_stop: bool = True
    runs_per_day_projection: int = Field(default=10, ge=1)


class BudgetExceeded(Exception):
    """Levee quand le budget (run ou journee) est atteint.

    Le CascadeExecutor capture cette exception pour emettre un verdict
    STOP avec justification detaillee et sortir proprement.
    """


class BudgetTracker:
    """Tracker de budget avec persistance quotidienne."""

    def __init__(self, config: BudgetConfig, daily_total_path: Path):
        self._config = config
        self._daily_total_path = Path(daily_total_path)
        self._daily_total: float = self._load_daily_total()

    @property
    def config(self) -> BudgetConfig:
        return self._config

    @property
    def daily_total(self) -> float:
        return self._daily_total

    def is_exceeded(self, current_cost: float) -> bool:
        """Vrai si le kill switch doit se declencher maintenant.

        Regles :
        - ``hard_stop=False`` : jamais de kill switch automatique
        - Sinon : depasse ``max_per_run_usd`` OU cumul quotidien + courant depasse ``max_per_day_usd``
        """
        if not self._config.hard_stop:
            return False
        if current_cost >= self._config.max_per_run_usd:
            return True
        if (self._daily_total + current_cost) >= self._config.max_per_day_usd:
            return True
        return False

    def is_warning(self, current_cost: float) -> bool:
        """Vrai si on a atteint le seuil d'alerte sur le run courant."""
        if self._config.max_per_run_usd <= 0:
            return False
        pct = (current_cost / self._config.max_per_run_usd) * 100
        return pct >= self._config.warn_at_percent

    def record(self, cost: float) -> None:
        """Incremente le cumul quotidien et persiste sur disque.

        En cas d'echec d'ecriture (FS readonly, permissions...), on log
        en silence et on continue en memoire seule.
        """
        self._daily_total += cost
        self._save_daily_total()

    def projected_monthly(self, current_cost: float) -> float:
        """Projection mensuelle basee sur le cout du run et la cadence supposee.

        Hypothese : on fait ``runs_per_day_projection`` runs par jour,
        chaque run coutant ``current_cost``.
        """
        return current_cost * 30 * self._config.runs_per_day_projection

    def explain(self, current_cost: float) -> str:
        """Message humain expliquant l'etat du budget (debug, logs)."""
        return (
            f"cout={current_cost:.4f}$ / max_run={self._config.max_per_run_usd:.2f}$ "
            f"({100 * current_cost / self._config.max_per_run_usd:.0f}%) | "
            f"cumul_jour={self._daily_total:.4f}$ / max_jour={self._config.max_per_day_usd:.2f}$ "
            f"({100 * (self._daily_total + current_cost) / self._config.max_per_day_usd:.0f}%)"
        )

    def _load_daily_total(self) -> float:
        """Charge le cumul du jour depuis le fichier JSON.

        Si le fichier date d'un autre jour, on recommence a zero.
        En cas d'erreur de lecture, on retourne 0.0 (degradation douce).
        """
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
        """Persiste le cumul quotidien. Echec silencieux tolere."""
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
            # FS readonly ou permissions : on accepte la degradation en memoire seule.
            pass