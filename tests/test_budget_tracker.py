"""Tests du kill switch budgétaire (spec V2 §9.2).

Structure : fixtures pytest, classes logiques, API BudgetTracker enrichie.
Fusion des tests Eddie (check_budget, warning, daily, exception) et des
tests existants (record, projected_monthly, explain, is_warning).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from goal_cascade.config import BudgetConfig
from goal_cascade.orchestrator.budget_tracker import BudgetExceeded, BudgetTracker


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def tracker(tmp_path: Path) -> BudgetTracker:
    config = BudgetConfig(
        max_per_run_usd=0.50,
        max_per_day_usd=10.00,
        warn_at_percent=80,
        hard_stop=True,
    )
    return BudgetTracker(config=config, runs_dir=tmp_path)


@pytest.fixture
def soft_tracker(tmp_path: Path) -> BudgetTracker:
    config = BudgetConfig(
        max_per_run_usd=0.50,
        max_per_day_usd=10.00,
        warn_at_percent=80,
        hard_stop=False,
    )
    return BudgetTracker(config=config, runs_dir=tmp_path)


# ── BudgetConfig validation ─────────────────────────────────────


class TestBudgetConfig:
    """Tests de validation de BudgetConfig."""

    def test_budget_config_has_sensible_defaults(self) -> None:
        config = BudgetConfig()
        assert config.max_per_run_usd == 0.50
        assert config.max_per_day_usd == 10.00
        assert config.warn_at_percent == 80
        assert config.hard_stop is True
        assert config.runs_per_day_projection == 10

    def test_budget_config_rejects_zero_max_per_run(self) -> None:
        with pytest.raises(ValueError):
            BudgetConfig(max_per_run_usd=0.0)

    def test_budget_config_rejects_warn_below_10(self) -> None:
        with pytest.raises(ValueError):
            BudgetConfig(warn_at_percent=5)


# ── Per-run budget ──────────────────────────────────────────────


class TestPerRunBudget:
    def test_under_budget_passes(self, tracker: BudgetTracker) -> None:
        tracker.check_budget("run-001", 0.10)  # Ne lève pas

    def test_at_budget_raises(self, tracker: BudgetTracker) -> None:
        with pytest.raises(BudgetExceeded, match="per_run"):
            tracker.check_budget("run-001", 0.50)

    def test_over_budget_raises(self, tracker: BudgetTracker) -> None:
        with pytest.raises(BudgetExceeded, match="per_run"):
            tracker.check_budget("run-001", 0.75)

    def test_soft_mode_does_not_raise(self, soft_tracker: BudgetTracker) -> None:
        soft_tracker.check_budget("run-001", 0.75)  # Ne lève pas

    def test_is_exceeded_returns_true(self, tracker: BudgetTracker) -> None:
        assert tracker.is_exceeded("run-001", 0.60) is True

    def test_is_exceeded_returns_false(self, tracker: BudgetTracker) -> None:
        assert tracker.is_exceeded("run-001", 0.10) is False


# ── Warning threshold ───────────────────────────────────────────


class TestWarningThreshold:
    @staticmethod
    def _has_budget_warning(
        caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
    ) -> bool:
        """Détecte 'budget_warning' dans caplog (logging std) OU stdout (structlog)."""
        if any("budget_warning" in r.message for r in caplog.records):
            return True
        return "budget_warning" in capsys.readouterr().out

    def test_warning_logged_at_80_percent(
        self, tracker: BudgetTracker, caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        tracker.check_budget("run-warn", 0.41)  # 82% de 0.50

        assert self._has_budget_warning(caplog, capsys)

    def test_warning_fired_only_once_per_run(
        self, tracker: BudgetTracker, caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        tracker.check_budget("run-once", 0.41)
        caplog.clear()
        capsys.readouterr()  # clear stdout
        tracker.check_budget("run-once", 0.42)

        assert not self._has_budget_warning(caplog, capsys)

    def test_is_warning_at_threshold(self, tracker: BudgetTracker) -> None:
        assert not tracker.is_warning(0.39)
        assert tracker.is_warning(0.40)

    def test_is_warning_disabled_when_max_per_run_zero(
        self, tmp_path: Path
    ) -> None:
        config = BudgetConfig.model_construct(max_per_run_usd=0, max_per_day_usd=10.0)
        tracker = BudgetTracker(config=config, runs_dir=tmp_path)

        assert not tracker.is_warning(5.0)


# ── Daily budget ────────────────────────────────────────────────


class TestDailyBudget:
    def _create_today_run(
        self, runs_dir: Path, run_id: str, cost: float
    ) -> None:
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        events = [
            {"event": "run_started", "timestamp_utc": f"{today}T00:00:00+00:00"},
            {"event": "provider_call_completed", "cost_usd": cost},
        ]
        (run_dir / "events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8",
        )

    def test_daily_budget_exceeded_raises(self, tmp_path: Path) -> None:
        config = BudgetConfig(
            max_per_run_usd=1.0, max_per_day_usd=0.10, hard_stop=True
        )
        tracker = BudgetTracker(config=config, runs_dir=tmp_path)

        self._create_today_run(tmp_path, "run-daily", 0.15)

        with pytest.raises(BudgetExceeded, match="per_day"):
            tracker.check_budget("run-new", 0.0)

    def test_daily_budget_under_limit_passes(self, tmp_path: Path) -> None:
        config = BudgetConfig(
            max_per_run_usd=1.0, max_per_day_usd=10.0, hard_stop=True
        )
        tracker = BudgetTracker(config=config, runs_dir=tmp_path)

        self._create_today_run(tmp_path, "run-ok", 0.05)
        tracker.check_budget("run-new", 0.01)  # Ne lève pas


# ── BudgetExceeded exception ────────────────────────────────────


class TestBudgetExceededException:
    def test_exception_message_contains_details(self) -> None:
        exc = BudgetExceeded("abc123", 0.75, 0.50, "per_run")

        assert "abc123" in str(exc)
        assert "0.750" in str(exc)
        assert "per_run" in str(exc)

    def test_exception_attributes(self) -> None:
        exc = BudgetExceeded("run-42", 1.50, 1.00, "per_day")

        assert exc.run_id == "run-42"
        assert exc.accumulated == 1.50
        assert exc.limit == 1.00
        assert exc.scope == "per_day"


# ── Record + persistance ────────────────────────────────────────


class TestRecordAndPersistence:
    def test_record_increments_daily_total(self, tracker: BudgetTracker) -> None:
        assert tracker.daily_total == 0.0
        tracker.record(0.05)
        assert tracker.daily_total == 0.05
        tracker.record(0.03)
        assert tracker.daily_total == 0.08

    def test_record_persists_to_daily_total_path(self, tmp_path: Path) -> None:
        daily_path = tmp_path / "budget_daily.json"
        config = BudgetConfig()
        tracker = BudgetTracker(
            config=config, runs_dir=tmp_path, daily_total_path=daily_path
        )

        tracker.record(0.10)

        assert daily_path.exists()
        data = json.loads(daily_path.read_text(encoding="utf-8"))
        assert data["date"] == date.today().isoformat()
        assert data["total"] == 0.10

    def test_record_tolerates_readonly_filesystem(self, tmp_path: Path) -> None:
        config = BudgetConfig()
        tracker = BudgetTracker(config=config, runs_dir=tmp_path)
        # Forcer un path inexistant pour simuler FS readonly
        tracker._daily_total_path = tmp_path / "nonexistent" / "nested" / "budget.json"

        tracker.record(0.10)  # Ne doit pas lever
        assert tracker.daily_total == 0.10


# ── Projection + explain ────────────────────────────────────────


class TestProjectionAndExplain:
    def test_projected_monthly_multiplies_correctly(
        self, tracker: BudgetTracker
    ) -> None:
        # 0.08 * 30 * 10 = 24.0
        assert tracker.projected_monthly(0.08) == 24.0

    def test_explain_returns_human_readable_string(
        self, tracker: BudgetTracker
    ) -> None:
        msg = tracker.explain(0.25)
        assert "coût=0.2500" in msg
        assert "max_run=0.50" in msg
        assert "max_jour=10.00" in msg


# ── Reset warnings ──────────────────────────────────────────────


class TestResetWarnings:
    def test_reset_clears_warned_runs(
        self, tracker: BudgetTracker, caplog: pytest.LogCaptureFixture
    ) -> None:
        tracker.check_budget("run-reset", 0.41)
        assert "run-reset" in tracker._warned_runs

        tracker.reset_warnings()
        assert len(tracker._warned_runs) == 0