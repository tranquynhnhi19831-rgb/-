import pandas as pd

from backtest.engine import BacktestEngine
from backtest.types import BacktestConfig, CandidateSignal
from risk.economic_viability import assess_round_trip_economics
from strategy.jianghe.pullback_event import evaluate_event_pullback_from_structure
from strategy.jianghe.pullback_score import score_event_pullback
from strategy.jianghe.types import MarketRegime, StructureSnapshot


def _event_fixture() -> pd.DataFrame:
    rows = [
        (100.00, 100.30, 99.80, 100.00),
        (100.00, 100.10, 99.50, 99.80),
        (99.80, 99.90, 99.00, 99.50),
        (99.50, 100.40, 99.40, 100.20),
        (100.20, 101.20, 100.00, 101.00),
        (101.00, 102.00, 100.80, 101.80),
        (101.80, 102.90, 101.60, 102.60),
        (102.60, 102.70, 101.90, 102.20),
        (102.20, 102.30, 101.40, 101.80),
        (101.80, 101.90, 101.10, 101.50),
        (101.50, 101.60, 100.80, 101.30),
        (101.30, 101.80, 101.10, 101.50),
        (101.50, 102.00, 101.30, 101.80),
        (101.80, 102.40, 101.70, 102.20),
        (102.20, 102.80, 102.10, 102.60),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _structure() -> StructureSnapshot:
    return StructureSnapshot(
        regime=MarketRegime.BULL_TREND,
        trend_efficiency=0.48,
        net_direction=1,
        last_high_1=101.8,
        last_high_2=102.9,
        last_low_1=99.8,
        last_low_2=100.75,
        swing_high_count=4,
        swing_low_count=4,
    )


def test_scored_pullback_keeps_structure_hard_and_strength_soft():
    frame = _event_fixture()
    evaluation = evaluate_event_pullback_from_structure(_structure(), frame)

    scored = score_event_pullback(evaluation, frame, min_quality_score=0.0)

    assert scored.eligible is True
    assert all(scored.hard_gates.values())
    assert 0.0 <= scored.quality_score <= 1.0
    assert set(scored.components) == {
        "context",
        "location",
        "impulse",
        "pullback_weakness",
        "trigger",
    }


def test_tight_stop_with_30u_notional_is_rejected_when_friction_exceeds_risk():
    result = assess_round_trip_economics(
        entry_price=100.0,
        stop_price=99.9,
        quantity=0.30,
        side="LONG",
        reward_risk=1.8,
        fee_rate=0.0004,
        slippage_bps=2.0,
        max_friction_to_risk=0.25,
    )

    assert result.allowed is False
    assert result.reason_code == "FRICTION_TOO_LARGE_VS_PLANNED_RISK"
    assert result.friction_to_planned_risk > 1.0


def test_wider_structural_stop_can_pass_same_cost_guard_without_increasing_risk():
    result = assess_round_trip_economics(
        entry_price=100.0,
        stop_price=98.0,
        quantity=0.25,
        side="LONG",
        reward_risk=1.8,
        fee_rate=0.0004,
        slippage_bps=2.0,
        max_friction_to_risk=0.25,
    )

    assert result.allowed is True
    assert result.planned_risk == 0.5
    assert result.friction_to_planned_risk < 0.25


def test_backtest_economic_gate_skips_bad_micro_stop_but_default_remains_unchanged():
    bars = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [100.1, 100.3, 100.4, 100.5],
            "low": [99.9, 99.8, 99.8, 99.9],
            "close": [100.0, 100.2, 100.3, 100.4],
        }
    )
    signal = CandidateSignal(
        index=0,
        setup="TEST",
        side="LONG",
        invalidation_reference=99.9,
    )

    baseline = BacktestEngine(
        BacktestConfig(reward_risk=1.8, max_hold_bars=3)
    ).run(bars, [signal])
    guarded = BacktestEngine(
        BacktestConfig(
            reward_risk=1.8,
            max_hold_bars=3,
            max_friction_to_planned_risk=0.25,
        )
    ).run(bars, [signal])

    assert baseline.metrics["trades"] == 1
    assert guarded.metrics["trades"] == 0
    assert guarded.metrics["economic_skips"] == 1
