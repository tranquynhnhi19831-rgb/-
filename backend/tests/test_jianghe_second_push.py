import pandas as pd

from strategy.jianghe.second_push import (
    SecondPushConfig,
    evaluate_second_push_failure_from_structure,
)
from strategy.jianghe.types import MarketRegime, StructureSnapshot


def _up_failure_execution() -> pd.DataFrame:
    rows = []
    price = 107.30

    # Push #1: clear, efficient attack into resistance.
    for move in (0.45, 0.42, 0.38, 0.35, 0.32, 0.28):
        open_ = price
        close = open_ + move
        rows.append((open_, close + 0.10, open_ - 0.06, close))
        price = close

    # Reset: opposing move creates separation before the second attempt.
    for move in (-0.38, -0.32, 0.10, -0.28):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.10, min(open_, close) - 0.10, close))
        price = close

    # Push #2: same direction, but shorter/slower/more overlapping and cannot improve the result.
    for move in (0.18, 0.16, 0.14, -0.10, 0.12, 0.08):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.10, min(open_, close) - 0.10, close))
        price = close

    # Opposite side takes control and breaks the last push's micro structure.
    for move in (-0.28, -0.34, -0.40):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.08, min(open_, close) - 0.08, close))
        price = close

    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _range_structure(resistance: float = 109.50, support: float = 106.50) -> StructureSnapshot:
    return StructureSnapshot(
        regime=MarketRegime.RANGE,
        trend_efficiency=0.18,
        net_direction=0,
        last_high_1=resistance - 0.20,
        last_high_2=resistance,
        last_low_1=support + 0.20,
        last_low_2=support,
        swing_high_count=5,
        swing_low_count=5,
    )


def _mirror_bear(df: pd.DataFrame, anchor: float = 220.0) -> pd.DataFrame:
    mirrored = pd.DataFrame()
    mirrored["open"] = anchor - df["open"]
    mirrored["close"] = anchor - df["close"]
    mirrored["high"] = anchor - df["low"]
    mirrored["low"] = anchor - df["high"]
    return mirrored[["open", "high", "low", "close"]]


def _mirrored_structure() -> StructureSnapshot:
    # Original resistance 109.50 mirrors into support 110.50 around anchor 220.
    return StructureSnapshot(
        regime=MarketRegime.RANGE,
        trend_efficiency=0.18,
        net_direction=0,
        last_high_1=113.30,
        last_high_2=113.50,
        last_low_1=110.70,
        last_low_2=110.50,
        swing_high_count=5,
        swing_low_count=5,
    )


def test_up_second_push_failure_becomes_short_reversal_candidate():
    result = evaluate_second_push_failure_from_structure(
        _range_structure(), _up_failure_execution()
    )

    assert result.candidate is True
    assert result.signal_state == "REVERSAL_CANDIDATE"
    assert result.weakness_detected is True
    assert result.side == "SHORT"
    assert result.push_direction == "UP"
    assert all(result.gates.values())
    assert result.push2_strength < result.push1_strength
    assert result.displacement_ratio < 1.0
    assert result.speed_ratio < 1.0
    assert result.acceptance_fraction == 0.0
    assert "SECOND_PUSH_WEAKER" in result.reason_codes
    assert "OPPOSITE_SIDE_TAKES_CONTROL" in result.reason_codes


def test_down_second_push_failure_is_symmetric_long_candidate():
    result = evaluate_second_push_failure_from_structure(
        _mirrored_structure(), _mirror_bear(_up_failure_execution())
    )

    assert result.candidate is True
    assert result.side == "LONG"
    assert result.push_direction == "DOWN"
    assert result.signal_state == "REVERSAL_CANDIDATE"
    assert result.invalidation_reference < result.level_price


def test_weak_second_push_without_opposite_trigger_is_watch_only():
    df = _up_failure_execution()
    # Replace the final trigger with small upward/flat bars: weakness remains, reversal is not confirmed.
    df.loc[16, ["open", "high", "low", "close"]] = [109.20, 109.32, 109.16, 109.26]
    df.loc[17, ["open", "high", "low", "close"]] = [109.26, 109.34, 109.20, 109.28]
    df.loc[18, ["open", "high", "low", "close"]] = [109.28, 109.35, 109.22, 109.30]

    result = evaluate_second_push_failure_from_structure(_range_structure(), df)

    assert result.candidate is False
    assert result.weakness_detected is True
    assert result.signal_state == "SECOND_PUSH_WEAKNESS"
    assert result.gates["FAILURE"] is True
    assert result.gates["TRIGGER"] is False
    assert "TRIGGER" in result.failed_gates


def test_failure_gate_rejects_second_push_not_weak_enough():
    cfg = SecondPushConfig(max_push2_to_push1_strength_ratio=0.60)
    result = evaluate_second_push_failure_from_structure(
        _range_structure(), _up_failure_execution(), cfg
    )

    assert result.candidate is False
    assert result.gates["FAILURE"] is False
    assert result.weakness_detected is False
    assert "SECOND_PUSH_NOT_WEAKER_BY_SCORE" in result.reason_codes


def test_failure_gate_rejects_accepted_breakout_beyond_level():
    df = _up_failure_execution()
    # Force three push-2 closes to remain beyond the structural resistance.
    df.loc[13, ["open", "high", "low", "close"]] = [109.45, 109.67, 109.38, 109.58]
    df.loc[14, ["open", "high", "low", "close"]] = [109.58, 109.72, 109.50, 109.63]
    df.loc[15, ["open", "high", "low", "close"]] = [109.63, 109.76, 109.55, 109.68]

    result = evaluate_second_push_failure_from_structure(_range_structure(), df)

    assert result.candidate is False
    assert result.gates["FAILURE"] is False
    assert result.acceptance_fraction > SecondPushConfig().max_acceptance_fraction
    assert "SECOND_PUSH_ACCEPTED_BEYOND_LEVEL" in result.reason_codes


def test_location_gate_requires_both_pushes_to_test_same_structural_level():
    result = evaluate_second_push_failure_from_structure(
        _range_structure(resistance=110.80), _up_failure_execution()
    )

    assert result.candidate is False
    assert result.gates["LOCATION"] is False
    assert "PUSH1_NOT_AT_LEVEL" in result.reason_codes
    assert "PUSH2_NOT_AT_LEVEL" in result.reason_codes


def test_unknown_context_is_rejected_cleanly():
    structure = StructureSnapshot(
        regime=MarketRegime.UNKNOWN,
        trend_efficiency=0.0,
        net_direction=0,
        last_high_1=None,
        last_high_2=None,
        last_low_1=None,
        last_low_2=None,
        swing_high_count=0,
        swing_low_count=0,
    )
    result = evaluate_second_push_failure_from_structure(structure, _up_failure_execution())

    assert result.candidate is False
    assert result.signal_state == "NO_SETUP"
    assert result.reason_codes == ("CONTEXT_NOT_SUPPORTED",)


def test_insufficient_history_returns_non_candidate_not_exception():
    result = evaluate_second_push_failure_from_structure(
        _range_structure(), _up_failure_execution().tail(8)
    )

    assert result.candidate is False
    assert result.reason_codes == ("INSUFFICIENT_EXECUTION_BARS",)
