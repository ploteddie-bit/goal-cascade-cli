"""Tests des schemas de reçu de coût (spec V2 §9).

Adapté du code proposé par Eddie — imports depuis schemas.models
(pas schemas.receipt qui n'existe pas dans notre architecture).
"""

from __future__ import annotations

from goal_cascade.schemas.models import LLMCallRecord, RunReceipt


def _make_call(
    role: str = "producer",
    provider: str = "mock",
    input_tokens: int = 100,
    output_tokens: int = 200,
    cache_read: int = 0,
    cost: float = 0.001,
    iteration: int = 1,
) -> LLMCallRecord:
    return LLMCallRecord(
        provider=provider,
        model="mock-small",
        iteration=iteration,
        role=role,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cost_usd=cost,
        latency_ms=150,
        timestamp_utc="2026-07-11T00:00:00+00:00",
    )


def test_run_receipt_from_calls_computes_totals() -> None:
    calls = [
        _make_call(role="producer", input_tokens=420, output_tokens=1850, cost=0.003),
        _make_call(
            role="critic",
            input_tokens=380,
            output_tokens=920,
            cache_read=420,
            cost=0.004,
            iteration=2,
        ),
        _make_call(
            role="arbiter",
            input_tokens=680,
            output_tokens=850,
            cache_read=510,
            cost=0.001,
            iteration=4,
        ),
    ]

    receipt = RunReceipt.from_calls(
        run_id="test-001",
        objective="Test receipt",
        verdict="STOP",
        duration_s=222.0,
        calls=calls,
    )

    assert receipt.total_cost_usd == 0.008
    assert receipt.total_iterations == 4
    assert receipt.cache_hit_rate > 0
    assert receipt.projected_monthly_cost == 0.008 * 10 * 30


def test_run_receipt_cache_hit_rate_zero_when_no_input() -> None:
    receipt = RunReceipt.from_calls(
        run_id="empty",
        objective="Empty",
        verdict="STOP",
        duration_s=0.0,
        calls=[],
    )

    assert receipt.cache_hit_rate == 0.0
    assert receipt.total_cost_usd == 0.0


def test_summary_lines_contains_key_fields() -> None:
    calls = [_make_call(cost=0.033)]
    receipt = RunReceipt.from_calls(
        run_id="a3f2c1",
        objective="Article LinkedIn",
        verdict="STOP",
        duration_s=222.0,
        calls=calls,
    )

    lines = receipt.summary_lines()
    text = "\n".join(lines)

    assert "STOP" in text
    assert "$0.033" in text
    assert "Cache hit rate" in text
    assert "Projeté" in text
