import pandas as pd

from strategy.jianghe.pullback_event import evaluate_event_pullback_from_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot


def _bull_event_fixture() -> pd.DataFrame:
    rows = [
        (100.00, 100.30, 99.80, 100.00),
        (100.00, 100.10, 99.50, 99.80),
        (99.80, 99.90, 99.00, 99.50),   # confirmed execution swing low L0
        (99.50, 100.40, 99.40, 100.20),
        (100.20, 101.20, 100.00, 101.00),
        (101.00, 102.00, 100.80, 101.80),
        (101.80, 102.90, 101.60, 102.60),  # confirmed swing high H1
        (102.60, 102.70, 101.90, 102.20),
        (102.20, 102.45, 101.80, 102.35),  # overlap/chop weakens the pullback leg
        (102.35, 102.45, 101.10, 101.50),
        (101.50, 101.60, 100.80, 101.30),  # confirmed pullback swing low L2
        (101.30, 101.80, 101.10, 101.50),
        (101.50, 102.00, 101.30, 101.80),
        (101.80, 102.40, 101.70, 102.20),
        (102.20, 102.80, 102.10, 102.60),  # closes above prior trigger highs
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _bull_structure() -> StructureSnapshot:
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


def _mirror(df: pd.DataFrame, anchor: float = 220.0) -> pd.DataFrame:
    out = pd.DataFrame()
    out["open"] = anchor - df["open"]
    out["close"] = anchor - df["close"]
    out["high"] = anchor - df["low"]
    out["low"] = anchor - df["high"]
    return out[["open", "high", "low", "close"]]


def _bear_structure() -> StructureSnapshot:
    # Bull support 100.75 mirrors to bear resistance 119.25 around anchor 220.
    return StructureSnapshot(
        regime=MarketRegime.BEAR_TREND,
        trend_efficiency=0.48,
        net_direction=-1,
        last_high_1=118.9,
        last_high_2=119.25,
        last_low_1=118.2,
        last_low_2=117.1,
        swing_high_count=4,
        swing_low_count=4,
    )


def test_event_pullback_uses_confirmed_variable_length_phases():
    result = evaluate_event_pullback_from_structure(_bull_structure(), _bull_event_fixture())

    assert result.candidate is True
    assert result.side == "LONG"
    assert result.impulse_start_index == 2
    assert result.impulse_end_index == 6
    assert result.pullback_end_index == 10
    assert result.impulse_bars == 5
    assert result.pullback_bars == 4
    assert result.trigger_bars == 4
    assert all(result.gates.values())
    assert result.pullback_strength < result.impulse_strength
    assert "EVENT_DRIVEN_PHASES" in result.reason_codes
    assert "POST_PULLBACK_MICRO_RECLAIM" in result.reason_codes


def test_event_pullback_is_symmetric_for_bear_context():
    result = evaluate_event_pullback_from_structure(_bear_structure(), _mirror(_bull_event_fixture()))

    assert result.candidate is True
    assert result.side == "SHORT"
    assert result.invalidation_reference > 119.0
    assert all(result.gates.values())


def test_event_pullback_rejects_context_direction_disagreement():
    structure = _bull_structure()
    misaligned = StructureSnapshot(
        regime=structure.regime,
        trend_efficiency=structure.trend_efficiency,
        net_direction=-1,
        last_high_1=structure.last_high_1,
        last_high_2=structure.last_high_2,
        last_low_1=structure.last_low_1,
        last_low_2=structure.last_low_2,
        swing_high_count=structure.swing_high_count,
        swing_low_count=structure.swing_low_count,
    )

    result = evaluate_event_pullback_from_structure(misaligned, _bull_event_fixture())

    assert result.candidate is False
    assert result.reason_codes == ("CONTEXT_DIRECTION_NOT_ALIGNED",)


def test_event_pullback_rejects_pullback_far_from_higher_timeframe_level():
    structure = _bull_structure()
    far = StructureSnapshot(
        regime=structure.regime,
        trend_efficiency=structure.trend_efficiency,
        net_direction=structure.net_direction,
        last_high_1=structure.last_high_1,
        last_high_2=structure.last_high_2,
        last_low_1=structure.last_low_1,
        last_low_2=97.0,
        swing_high_count=structure.swing_high_count,
        swing_low_count=structure.swing_low_count,
    )

    result = evaluate_event_pullback_from_structure(far, _bull_event_fixture())

    assert result.candidate is False
    assert result.gates["LEVEL"] is False
