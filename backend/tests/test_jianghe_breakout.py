import pandas as pd

from strategy.jianghe.breakout import (
    BreakoutConfig,
    evaluate_breakout_continuation_from_structure,
)
from strategy.jianghe.types import MarketRegime, StructureSnapshot


def _bull_execution() -> pd.DataFrame:
    # 12 pressure bars: repeated tests of 110 with visibly shrinking ranges.
    rows = [
        (108.50, 108.90, 108.20, 108.70),
        (108.70, 109.10, 108.40, 108.90),
        (108.90, 109.25, 108.65, 109.05),
        (109.05, 109.40, 108.80, 109.20),
        (109.20, 109.55, 109.00, 109.35),
        (109.35, 109.70, 109.15, 109.50),
        (109.50, 109.78, 109.35, 109.62),
        (109.62, 109.90, 109.48, 109.72),
        (109.72, 109.94, 109.58, 109.78),
        (109.78, 109.98, 109.64, 109.84),
        (109.84, 110.00, 109.72, 109.88),
        (109.88, 110.02, 109.78, 109.92),
        # 2 breakout-window bars: decisive closes outside structural resistance.
        (109.92, 110.50, 109.85, 110.42),
        (110.42, 110.80, 110.35, 110.72),
        # 3 follow-through bars: price accepts above the old resistance.
        (110.70, 111.00, 110.62, 110.94),
        (110.94, 111.18, 110.85, 111.10),
        (111.10, 111.40, 111.02, 111.32),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _mirror_bear(df: pd.DataFrame, anchor: float = 220.0) -> pd.DataFrame:
    mirrored = pd.DataFrame()
    mirrored["open"] = anchor - df["open"]
    mirrored["close"] = anchor - df["close"]
    mirrored["high"] = anchor - df["low"]
    mirrored["low"] = anchor - df["high"]
    return mirrored[["open", "high", "low", "close"]]


def _bull_structure() -> StructureSnapshot:
    return StructureSnapshot(
        regime=MarketRegime.BULL_TREND,
        trend_efficiency=0.52,
        net_direction=1,
        last_high_1=109.20,
        last_high_2=110.00,
        last_low_1=106.80,
        last_low_2=107.60,
        swing_high_count=4,
        swing_low_count=4,
    )


def _bear_structure() -> StructureSnapshot:
    return StructureSnapshot(
        regime=MarketRegime.BEAR_TREND,
        trend_efficiency=0.52,
        net_direction=-1,
        last_high_1=113.20,
        last_high_2=112.40,
        last_low_1=110.80,
        last_low_2=110.00,
        swing_high_count=4,
        swing_low_count=4,
    )


def test_bull_breakout_candidate_passes_all_gates():
    result = evaluate_breakout_continuation_from_structure(_bull_structure(), _bull_execution())

    assert result.candidate is True
    assert result.side == "LONG"
    assert result.gates == {"CONTEXT": True, "PRESSURE": True, "BREAKOUT": True, "HOLD": True}
    assert result.failed_gates == ()
    assert result.test_count >= 2
    assert result.compression_ratio < 1
    assert result.breakout_extension_atr > 0
    assert result.hold_fraction == 1.0
    assert "REPEATED_LEVEL_TESTS" in result.reason_codes
    assert "BREAKOUT_CLOSE_CONFIRMED" in result.reason_codes
    assert "BREAKOUT_ACCEPTED_OUTSIDE_LEVEL" in result.reason_codes


def test_bear_breakout_candidate_is_symmetric():
    result = evaluate_breakout_continuation_from_structure(
        _bear_structure(), _mirror_bear(_bull_execution())
    )

    assert result.candidate is True
    assert result.side == "SHORT"
    assert all(result.gates.values())
    assert result.entry_reference < result.level_price
    assert result.invalidation_reference > result.level_price


def test_pressure_gate_requires_repeated_level_tests():
    cfg = BreakoutConfig(min_tests=6)
    result = evaluate_breakout_continuation_from_structure(_bull_structure(), _bull_execution(), cfg)

    assert result.candidate is False
    assert result.gates["PRESSURE"] is False
    assert "INSUFFICIENT_LEVEL_TESTS" in result.reason_codes


def test_pressure_gate_can_require_real_range_compression():
    cfg = BreakoutConfig(max_compression_ratio=0.40)
    result = evaluate_breakout_continuation_from_structure(_bull_structure(), _bull_execution(), cfg)

    assert result.candidate is False
    assert result.gates["PRESSURE"] is False
    assert "NO_PREBREAK_COMPRESSION" in result.reason_codes


def test_wick_through_level_without_close_is_not_a_breakout():
    execution = _bull_execution()
    execution.loc[12, ["open", "high", "low", "close"]] = [109.92, 110.55, 109.84, 109.96]
    execution.loc[13, ["open", "high", "low", "close"]] = [109.96, 110.62, 109.88, 109.98]

    result = evaluate_breakout_continuation_from_structure(_bull_structure(), execution)

    assert result.candidate is False
    assert result.gates["BREAKOUT"] is False
    assert result.breakout_index is None
    assert "BREAKOUT_CLOSE_NOT_CONFIRMED" in result.reason_codes


def test_failed_breakout_reentry_is_rejected_even_after_initial_break():
    execution = _bull_execution()
    execution.loc[14, ["open", "high", "low", "close"]] = [110.68, 110.75, 109.60, 109.72]

    result = evaluate_breakout_continuation_from_structure(_bull_structure(), execution)

    assert result.candidate is False
    assert result.gates["BREAKOUT"] is True
    assert result.gates["HOLD"] is False
    assert result.hold_fraction < 1.0
    assert "FAILED_BREAKOUT_REENTRY" in result.reason_codes


def test_context_gate_rejects_range_market():
    structure = StructureSnapshot(
        regime=MarketRegime.RANGE,
        trend_efficiency=0.10,
        net_direction=0,
        last_high_1=110.1,
        last_high_2=110.0,
        last_low_1=108.0,
        last_low_2=108.1,
        swing_high_count=4,
        swing_low_count=4,
    )
    result = evaluate_breakout_continuation_from_structure(structure, _bull_execution())

    assert result.candidate is False
    assert result.side is None
    assert result.reason_codes == ("CONTEXT_NOT_TRENDING",)


def test_insufficient_execution_history_returns_non_candidate():
    result = evaluate_breakout_continuation_from_structure(
        _bull_structure(), _bull_execution().tail(8)
    )

    assert result.candidate is False
    assert result.reason_codes == ("INSUFFICIENT_EXECUTION_BARS",)
