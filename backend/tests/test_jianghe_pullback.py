import pandas as pd

from strategy.jianghe.pullback import (
    PullbackConfig,
    evaluate_trend_pullback_from_structure,
)
from strategy.jianghe.types import MarketRegime, StructureSnapshot


def _bull_execution() -> pd.DataFrame:
    rows = []
    price = 104.30

    # Strong trend-direction impulse.
    for _ in range(8):
        open_ = price
        close = open_ + 0.22
        rows.append((open_, close + 0.08, open_ - 0.05, close))
        price = close

    # Choppy opposing pullback: meaningful retracement, but lower directional efficiency.
    for move in (-0.50, 0.25, -0.55, 0.30, -0.65):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.12, min(open_, close) - 0.12, close))
        price = close

    # Trend-direction re-acceleration that reclaims the last pullback bar.
    for move in (0.30, 0.38, 0.42):
        open_ = price
        close = open_ + move
        rows.append((open_, close + 0.08, open_ - 0.06, close))
        price = close

    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _mirror_bear(df: pd.DataFrame, anchor: float = 210.0) -> pd.DataFrame:
    mirrored = pd.DataFrame()
    mirrored["open"] = anchor - df["open"]
    mirrored["close"] = anchor - df["close"]
    mirrored["high"] = anchor - df["low"]
    mirrored["low"] = anchor - df["high"]
    return mirrored[["open", "high", "low", "close"]]


def _bull_structure() -> StructureSnapshot:
    return StructureSnapshot(
        regime=MarketRegime.BULL_TREND,
        trend_efficiency=0.46,
        net_direction=1,
        last_high_1=106.8,
        last_high_2=107.6,
        last_low_1=103.9,
        last_low_2=104.7,
        swing_high_count=4,
        swing_low_count=4,
    )


def _bear_structure() -> StructureSnapshot:
    return StructureSnapshot(
        regime=MarketRegime.BEAR_TREND,
        trend_efficiency=0.46,
        net_direction=-1,
        last_high_1=106.1,
        last_high_2=105.3,
        last_low_1=103.2,
        last_low_2=102.4,
        swing_high_count=4,
        swing_low_count=4,
    )


def test_bull_trend_pullback_candidate_passes_all_four_gates():
    result = evaluate_trend_pullback_from_structure(_bull_structure(), _bull_execution())

    assert result.candidate is True
    assert result.side == "LONG"
    assert result.gates == {"CONTEXT": True, "LEVEL": True, "STATE": True, "TRIGGER": True}
    assert result.failed_gates == ()
    assert result.pullback_strength < result.impulse_strength
    assert result.trigger_strength > result.pullback_strength
    assert "AT_STRUCTURAL_LEVEL" in result.reason_codes
    assert "TREND_DIRECTION_REACCELERATION" in result.reason_codes


def test_bear_trend_pullback_candidate_is_symmetric():
    execution = _mirror_bear(_bull_execution())
    result = evaluate_trend_pullback_from_structure(_bear_structure(), execution)

    assert result.candidate is True
    assert result.side == "SHORT"
    assert all(result.gates.values())
    assert result.invalidation_reference > result.level_price
    assert result.entry_reference < result.level_price


def test_level_gate_fails_when_pullback_never_reaches_structural_area():
    cfg = PullbackConfig(level_tolerance_atr=0.10)
    result = evaluate_trend_pullback_from_structure(_bull_structure(), _bull_execution(), cfg)

    assert result.candidate is False
    assert result.gates["LEVEL"] is False
    assert "LEVEL" in result.failed_gates
    assert "STRUCTURAL_LEVEL_TOO_FAR" in result.reason_codes


def test_level_gate_fails_when_structural_support_is_invalidated():
    execution = _bull_execution()
    # Force a deep break of the higher-timeframe support during the pullback segment.
    execution.loc[12, "low"] = 103.50
    execution.loc[12, "close"] = 104.20
    execution.loc[12, "open"] = 105.20
    execution.loc[12, "high"] = 105.30

    result = evaluate_trend_pullback_from_structure(_bull_structure(), execution)

    assert result.candidate is False
    assert result.gates["LEVEL"] is False
    assert "STRUCTURAL_LEVEL_INVALIDATED" in result.reason_codes


def test_context_gate_rejects_range_market():
    structure = StructureSnapshot(
        regime=MarketRegime.RANGE,
        trend_efficiency=0.12,
        net_direction=0,
        last_high_1=107.0,
        last_high_2=106.8,
        last_low_1=104.0,
        last_low_2=104.2,
        swing_high_count=4,
        swing_low_count=4,
    )
    result = evaluate_trend_pullback_from_structure(structure, _bull_execution())

    assert result.candidate is False
    assert result.side is None
    assert result.gates["CONTEXT"] is False
    assert result.reason_codes == ("CONTEXT_NOT_TRENDING",)


def test_insufficient_execution_history_returns_non_candidate_not_exception():
    short_df = _bull_execution().tail(8)
    result = evaluate_trend_pullback_from_structure(_bull_structure(), short_df)

    assert result.candidate is False
    assert result.reason_codes == ("INSUFFICIENT_EXECUTION_BARS",)
