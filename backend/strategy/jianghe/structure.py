from __future__ import annotations

import pandas as pd

from strategy.jianghe.types import MarketRegime, StructureSnapshot, SwingPoint

REQUIRED_COLUMNS = {"high", "low", "close"}


def _validate(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")


def find_confirmed_swings(
    df: pd.DataFrame,
    left: int = 2,
    right: int = 2,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """Find confirmed fractal swing highs/lows without using future bars silently.

    A pivot at index i is only confirmed at i + right. Consumers must respect
    `confirmed_at` during backtests to avoid look-ahead bias.
    """
    _validate(df)
    if left < 1 or right < 1:
        raise ValueError("left/right swing windows must be >= 1")
    if len(df) < left + right + 1:
        return [], []

    highs: list[SwingPoint] = []
    lows: list[SwingPoint] = []
    high_values = df["high"].astype(float).tolist()
    low_values = df["low"].astype(float).tolist()

    for i in range(left, len(df) - right):
        high_window = high_values[i - left : i + right + 1]
        low_window = low_values[i - left : i + right + 1]
        current_high = high_values[i]
        current_low = low_values[i]

        # Strict comparison avoids double-counting flat plateaus as multiple pivots.
        other_highs = high_window[:left] + high_window[left + 1 :]
        other_lows = low_window[:left] + low_window[left + 1 :]

        if all(current_high > value for value in other_highs):
            highs.append(
                SwingPoint(
                    index=i,
                    confirmed_at=i + right,
                    price=current_high,
                    kind="HIGH",
                )
            )
        if all(current_low < value for value in other_lows):
            lows.append(
                SwingPoint(
                    index=i,
                    confirmed_at=i + right,
                    price=current_low,
                    kind="LOW",
                )
            )

    return highs, lows


def trend_efficiency(close: pd.Series, lookback: int = 20) -> tuple[float, int]:
    """Return Kaufman-style path efficiency and signed net direction."""
    values = close.astype(float).tail(max(2, lookback)).tolist()
    if len(values) < 2:
        return 0.0, 0

    net = values[-1] - values[0]
    path = sum(abs(values[i] - values[i - 1]) for i in range(1, len(values)))
    efficiency = abs(net) / path if path > 0 else 0.0
    direction = 1 if net > 0 else -1 if net < 0 else 0
    return float(max(0.0, min(1.0, efficiency))), direction


def classify_structure(
    df: pd.DataFrame,
    swing_left: int = 2,
    swing_right: int = 2,
    efficiency_lookback: int = 20,
) -> StructureSnapshot:
    """Classify HH/HL, LH/LL or mixed structure.

    Regime is based on confirmed swing structure only. `trend_efficiency` is
    returned as a separate feature so future experiments can test whether it
    adds information instead of hiding it inside a hard-coded filter.
    """
    _validate(df)
    highs, lows = find_confirmed_swings(df, swing_left, swing_right)
    efficiency, direction = trend_efficiency(df["close"], efficiency_lookback)

    regime = MarketRegime.UNKNOWN
    last_high_1 = last_high_2 = last_low_1 = last_low_2 = None

    if len(highs) >= 2:
        last_high_1 = highs[-2].price
        last_high_2 = highs[-1].price
    if len(lows) >= 2:
        last_low_1 = lows[-2].price
        last_low_2 = lows[-1].price

    if None not in (last_high_1, last_high_2, last_low_1, last_low_2):
        higher_high = last_high_2 > last_high_1
        higher_low = last_low_2 > last_low_1
        lower_high = last_high_2 < last_high_1
        lower_low = last_low_2 < last_low_1

        if higher_high and higher_low:
            regime = MarketRegime.BULL_TREND
        elif lower_high and lower_low:
            regime = MarketRegime.BEAR_TREND
        else:
            regime = MarketRegime.RANGE

    return StructureSnapshot(
        regime=regime,
        trend_efficiency=efficiency,
        net_direction=direction,
        last_high_1=last_high_1,
        last_high_2=last_high_2,
        last_low_1=last_low_1,
        last_low_2=last_low_2,
        swing_high_count=len(highs),
        swing_low_count=len(lows),
    )
