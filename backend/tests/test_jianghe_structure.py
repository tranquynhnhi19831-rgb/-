import pandas as pd

from strategy.jianghe.structure import classify_structure, find_confirmed_swings
from strategy.jianghe.types import MarketRegime


def frame(close, high, low):
    return pd.DataFrame({"close": close, "high": high, "low": low})


def test_confirmed_swings_expose_confirmation_bar():
    df = frame(
        close=[100, 104, 102, 107, 104, 110, 107],
        high=[101, 105, 103, 108, 105, 111, 108],
        low=[99, 103, 101, 106, 103, 109, 106],
    )
    highs, lows = find_confirmed_swings(df, left=1, right=1)

    assert highs
    assert lows
    assert all(point.confirmed_at == point.index + 1 for point in highs + lows)


def test_classifies_higher_highs_and_higher_lows_as_bull_trend():
    df = frame(
        close=[100, 104, 102, 107, 104, 110, 107],
        high=[101, 105, 103, 108, 105, 111, 108],
        low=[99, 103, 101, 106, 103, 109, 106],
    )

    snapshot = classify_structure(df, swing_left=1, swing_right=1)
    assert snapshot.regime == MarketRegime.BULL_TREND
    assert snapshot.last_high_2 > snapshot.last_high_1
    assert snapshot.last_low_2 > snapshot.last_low_1


def test_classifies_lower_highs_and_lower_lows_as_bear_trend():
    df = frame(
        close=[110, 106, 108, 103, 106, 100, 103],
        high=[111, 107, 109, 104, 107, 101, 104],
        low=[109, 105, 107, 102, 105, 99, 102],
    )

    snapshot = classify_structure(df, swing_left=1, swing_right=1)
    assert snapshot.regime == MarketRegime.BEAR_TREND
    assert snapshot.last_high_2 < snapshot.last_high_1
    assert snapshot.last_low_2 < snapshot.last_low_1


def test_insufficient_confirmed_swings_is_unknown():
    df = frame(
        close=[100, 101, 102],
        high=[101, 102, 103],
        low=[99, 100, 101],
    )

    snapshot = classify_structure(df, swing_left=1, swing_right=1)
    assert snapshot.regime == MarketRegime.UNKNOWN
