"""Tests unitaires pour le budget tracker et le kill switch.

Couvre :
- is_exceeded declenche quand max_per_run_usd atteint
- is_exceeded declenche quand cumul jour + courant atteint max_per_day_usd
- hard_stop=False desactive le kill switch
- is_warning au seuil warn_at_percent
- record() incremente le cumul quotidien et persiste sur disque
- _load_daily_total ignore un fichier d'un autre jour
- projected_monthly() multiplie correctement
- tolerance aux erreurs d'ecriture (FS readonly)
- RunReceipt valide les champs caches
- Build_receipt du CascadeExecutor calcule cache_hit_rate et projected_monthly
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from goal_cascade.orchestrator.budget_tracker import (
    BudgetConfig,
    BudgetExceeded,
    BudgetTracker,
)
from goal_cascade.schemas.models import (
    CascadeState,
    LLMCallRecord,
    RunReceipt,
    Verdict,
)


# ---------- BudgetConfig ----------

def test_budget_config_has_sensible_defaults() -> None:
    config = BudgetConfig()
    assert config.max_per_run_usd == 0.50
    assert config.max_per_day_usd == 10.00
    assert config.warn_at_percent == 80
    assert config.hard_stop is True
    assert config.runs_per_day_projection == 10


def test_budget_config_rejects_zero_max_per_run_usd() -> None:
    with pytest.raises(ValueError):
        BudgetConfig(max_per_run_usd=0.0)


def test_budget_config_rejects_warn_above_100() -> None:
    with pytest.raises(ValueError):
        BudgetConfig(warn_at_percent=150)


# ---------- BudgetTracker.is_exceeded ----------

def test_is_exceeded_triggers_when_max_per_run_usd_reached(tmp_path: Path) -> None:
    config = BudgetConfig(max_per_run_usd=0.10, max_per_day_usd=10.0)
    tracker = BudgetTracker(config, tmp_path / "budget.json")

    assert not tracker.is_exceeded(0.05)
    assert not tracker.is_exceeded(0.099)
    assert tracker.is_exceeded(0.10)
    assert tracker.is_exceeded(0.20)


def test_is_exceeded_triggers_when_daily_cumulative_reached(tmp_path: Path) -> None:
    """Si le cumul du jour + courant depasse max_per_day_usd, kill switch."""
    daily = tmp_path / "budget.json"
    daily.write_text(json.dumps({
        "date": date.today().isoformat(),
        "total": 9.50,
    }), encoding="utf-8")
    config = BudgetConfig(max_per_run_usd=1.0, max_per_day_usd=10.0)
    tracker = BudgetTracker(config, daily)

    assert not tracker.is_exceeded(0.40)  # 9.50 + 0.40 = 9.90
    assert tracker.is_exceeded(0.60)    # 9.50 + 0.60 = 10.10


def test_is_exceeded_disabled_when_hard_stop_false(tmp_path: Path) -> None:
    config = BudgetConfig(max_per_run_usd=0.10, hard_stop=False)
    tracker = BudgetTracker(config, tmp_path / "budget.json")

    assert not tracker.is_exceeded(0.05)
    assert not tracker.is_exceeded(100.0)


# ---------- BudgetTracker.is_warning ----------

def test_is_warning_at_threshold(tmp_path: Path) -> None:
    config = BudgetConfig(max_per_run_usd=1.0, warn_at_percent=80)
    tracker = BudgetTracker(config, tmp_path / "budget.json")

    assert not tracker.is_warning(0.79)
    assert tracker.is_warning(0.80)
    assert tracker.is_warning(1.50)


def test_is_warning_disabled_when_max_per_run_usd_zero(tmp_path: Path) -> None:
    """Configuration defensive : si max_per_run_usd=0 (mal configure), pas de warning."""
    # On contourne le validator Pydantic pour creer ce cas limite.
    config = BudgetConfig.model_construct(max_per_run_usd=0, max_per_day_usd=10.0)
    tracker = BudgetTracker(config, tmp_path / "budget.json")

    assert not tracker.is_warning(5.0)


# ---------- BudgetTracker.record + persistance ----------

def test_record_increments_daily_total_and_persists(tmp_path: Path) -> None:
    daily = tmp_path / "budget.json"
    config = BudgetConfig()
    tracker = BudgetTracker(config, daily)

    assert tracker.daily_total == 0.0
    tracker.record(0.05)
    assert tracker.daily_total == 0.05

    # Persistance immediate
    persisted = json.loads(daily.read_text(encoding="utf-8"))
    assert persisted["date"] == date.today().isoformat()
    assert persisted["total"] == 0.05


def test_record_tolerates_readonly_filesystem(tmp_path: Path) -> None:
    """Si l'ecriture echoue (FS readonly), pas d'exception levee."""
    # Sur Windows le mode readonly est legerement different ; on simule via Path
    # qui leve OSError : on utilise un dossier qui n'existe pas en read-only.
    config = BudgetConfig()
    # Sur linux, on peut chmod apres creation. Pour rester portable, on utilise
    # un Path sous un dossier inexistant comme parent (mkdir part=True va echouer
    # si on est sous readonly). Strategie : creer le tracker avec un path valide
    # mais faire pointer le path apres coup vers un dossier sans permission.
    daily = tmp_path / "budget.json"
    tracker = BudgetTracker(config, daily)

    # Force _save_daily_total a echouer : on remplace l'attribut par un chemin
    # qui ne peut pas etre cree.
    tracker._daily_total_path = tmp_path / "nonexistent_dir_xyz" / "nested" / "budget.json"
    tracker.record(0.10)  # ne doit pas lever
    assert tracker.daily_total == 0.10


def test_load_daily_total_ignores_old_date(tmp_path: Path) -> None:
    daily = tmp_path / "budget.json"
    daily.write_text(json.dumps({
        "date": "2020-01-01",  # tres ancien
        "total": 999.99,
    }), encoding="utf-8")
    config = BudgetConfig()
    tracker = BudgetTracker(config, daily)

    assert tracker.daily_total == 0.0  # ignore le fichier d'un autre jour


def test_load_daily_total_tolerates_malformed_json(tmp_path: Path) -> None:
    daily = tmp_path / "budget.json"
    daily.write_text("{ pas du json valide", encoding="utf-8")
    config = BudgetConfig()
    tracker = BudgetTracker(config, daily)

    assert tracker.daily_total == 0.0


# ---------- BudgetTracker.projected_monthly + explain ----------

def test_projected_monthly_multiplies_correctly(tmp_path: Path) -> None:
    config = BudgetConfig(runs_per_day_projection=10)
    tracker = BudgetTracker(config, tmp_path / "budget.json")

    # 0.08 * 30 * 10 = 24.0
    assert tracker.projected_monthly(0.08) == 24.0


def test_explain_returns_human_readable_string(tmp_path: Path) -> None:
    config = BudgetConfig(max_per_run_usd=1.0, max_per_day_usd=10.0)
    tracker = BudgetTracker(config, tmp_path / "budget.json")

    msg = tracker.explain(0.50)
    assert "cout=0.5000" in msg
    assert "max_run=1.00" in msg
    assert "max_jour=10.00" in msg


# ---------- RunReceipt schema ----------

def test_run_receipt_validates_minimal_fields() -> None:
    receipt = RunReceipt(
        run_id="abc123",
        objective="Test",
        total_iterations=4,
        final_verdict="STOP",
        total_duration_s=12.5,
        calls=[],
        total_cost_usd=0.087,
        cache_hit_rate=0.37,
        projected_monthly_cost=10.0,
    )
    assert receipt.run_id == "abc123"
    assert receipt.cache_hit_rate == 0.37


def test_run_receipt_serializes_to_json() -> None:
    receipt = RunReceipt(
        run_id="abc",
        objective="x",
        total_iterations=1,
        final_verdict="STOP",
        total_duration_s=1.0,
        calls=[],
        total_cost_usd=0.0,
        cache_hit_rate=0.0,
        projected_monthly_cost=0.0,
    )
    payload = receipt.model_dump_json()
    parsed = json.loads(payload)
    assert parsed["run_id"] == "abc"
    assert parsed["cache_hit_rate"] == 0.0


# ---------- LLMCallRecord avec cache ----------

def test_llm_call_record_supports_cache_tokens() -> None:
    record = LLMCallRecord(
        provider="anthropic",
        model="claude-haiku",
        iteration=1,
        role="producer",
        input_tokens=500,
        output_tokens=200,
        cache_read_tokens=300,
        cache_write_tokens=200,
    )
    assert record.cache_read_tokens == 300
    assert record.cache_write_tokens == 200


# ---------- Build receipt via CascadeExecutor ----------

def test_cascade_executor_build_receipt_calculates_cache_hit_rate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le receipt agrege cache_read_tokens / total_input_tokens."""
    # On importe ici pour eviter les imports circulaires au chargement du test.
    from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
    from goal_cascade.providers.base import LLMResponse
    from goal_cascade.providers.mock import MockProvider
    from goal_cascade.prompts import PromptLoader

    # Provider mock sans cout, synthesizer distinct
    provider = MockProvider()
    synthesizer = MockProvider()
    executor = CascadeExecutor(
        provider=provider,
        synthesizer_provider=synthesizer,
        prompt_loader=PromptLoader(),
    )

    # Construire un etat avec un historique connu
    state = CascadeState(run_id="test", objective="x")
    state.history = [
        LLMCallRecord(
            provider="anthropic", model="haiku", iteration=1, role="producer",
            input_tokens=1000, output_tokens=200, cost_usd=0.0,
            cache_read_tokens=300,
        ),
        LLMCallRecord(
            provider="anthropic", model="haiku", iteration=2, role="critic",
            input_tokens=500, output_tokens=100, cost_usd=0.0,
            cache_read_tokens=100,
        ),
    ]
    state.accumulated_cost = 0.0
    state.current_iteration = 2
    state.final_verdict = Verdict(decision="STOP", justification="ok")

    receipt = executor.build_receipt(state, duration_s=2.5)

    # total_input = 1000 + 500 = 1500, cache_read = 300 + 100 = 400
    # cache_hit_rate = 400 / 1500 ≈ 0.2667
    assert abs(receipt.cache_hit_rate - 400 / 1500) < 0.001
    assert receipt.total_cost_usd == 0.0
    assert receipt.total_iterations == 2
    assert receipt.final_verdict == "STOP"
    # projected_monthly_cost : 0.0 * 30 * 10 = 0.0 (pas de budget_tracker)
    assert receipt.projected_monthly_cost == 0.0


def test_cascade_executor_build_receipt_handles_zero_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pas d'appels = cache_hit_rate 0.0 sans division par zero."""
    from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
    from goal_cascade.providers.mock import MockProvider
    from goal_cascade.prompts import PromptLoader

    executor = CascadeExecutor(
        provider=MockProvider(),
        synthesizer_provider=MockProvider(),
        prompt_loader=PromptLoader(),
    )

    state = CascadeState(run_id="empty", objective="x")
    state.history = []
    state.accumulated_cost = 0.0
    state.current_iteration = 0

    receipt = executor.build_receipt(state, duration_s=0.0)

    assert receipt.cache_hit_rate == 0.0
    assert receipt.total_iterations == 0


def test_cascade_executor_build_receipt_uses_budget_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si un BudgetTracker est attaché, projected_monthly utilise sa config."""
    from goal_cascade.orchestrator.cascade_executor import CascadeExecutor
    from goal_cascade.providers.mock import MockProvider
    from goal_cascade.prompts import PromptLoader
    from goal_cascade.schemas.models import LLMCallRecord

    budget = BudgetTracker(
        config=BudgetConfig(runs_per_day_projection=5),
        daily_total_path=tmp_path / "budget.json",
    )

    executor = CascadeExecutor(
        provider=MockProvider(),
        synthesizer_provider=MockProvider(),
        prompt_loader=PromptLoader(),
        budget_tracker=budget,
    )

    state = CascadeState(run_id="r", objective="x")
    state.accumulated_cost = 0.10
    # Ajouter un appel à l'historique pour que from_calls() calcule le coût
    state.history.append(
        LLMCallRecord(
            provider="mock",
            model="mock-small",
            iteration=1,
            role="producer",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.10,
        )
    )

    receipt = executor.build_receipt(state, duration_s=1.0)

    # 0.10 * 30 * 5 = 15.0
    assert receipt.projected_monthly_cost == 15.0