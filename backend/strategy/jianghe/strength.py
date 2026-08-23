from __future__ import annotations

import pandas as pd

from strategy.jianghe.types import StrengthSnapshot, StrengthTransition

REQUIRED_COLUMNS = {"open", "high", "low", "close"}


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _validate(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    if len(df) < 2:
        raise ValueError("strength calculation requires at least two bars")


def _average_true_range(df: pd.DataFrame) -> float:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.mean())
    return atr if atr > 0 else 1e-12


def _overlap_ratio(df: pd.DataFrame) -> float:
    highs = df["high"].astype(float).tolist()
    lows = df["low"].astype(float).tolist()
    ratios: list[float] = []

    for i in range(1, len(df)):
        overlap = max(0.0, min(highs[i - 1], highs[i]) - max(lows[i - 1], lows[i]))
        prev_range = max(0.0, highs[i - 1] - lows[i - 1])
        curr_range = max(0.0, highs[i] - lows[i])
        denominator = min(prev_range, curr_range)
        if denominator > 0:
            ratios.append(_clip01(overlap / denominator))

    return float(sum(ratios) / len(ratios)) if ratios else 0.0


def _trend_efficiency(close: pd.Series) -> float:
    values = close.astype(float).tolist()
    net = abs(values[-1] - values[0])
    path = sum(abs(values[i] - values[i - 1]) for i in range(1, len(values)))
    return _clip01(net / path) if path > 0 else 0.0


def calculate_directional_strength(
    df: pd.DataFrame,
    lookback: int = 8,
) -> StrengthSnapshot:
    """Translate Jianghe-style price 'strength/weakness' into auditable features.

    This is an experimental quantitative translation (evidence grade D), not a
    claim that Jianghe uses these exact formulas, weights or thresholds.

    Features intentionally remain visible instead of collapsing directly into
    a buy/sell signal:
      - ATR-normalized displacement
      - ATR-normalized speed
      - candle body efficiency
      - directional candle consistency
      - directional close location
      - consecutive-bar overlap
      - path/trend efficiency
    """
    _validate(df)
    window = df.tail(max(2, lookback)).copy()

    open_ = window["open"].astype(float)
    high = window["high"].astype(float)
    low = window["low"].astype(float)
    close = window["close"].astype(float)

    bars = len(window)
    net_move = float(close.iloc[-1] - close.iloc[0])
    direction = 1 if net_move > 0 else -1 if net_move < 0 else 0
    atr = _average_true_range(window)

    displacement_atr = abs(net_move) / atr
    speed_atr_per_bar = displacement_atr / max(1, bars - 1)

    total_range = float((high - low).abs().sum())
    total_body = float((close - open_).abs().sum())
    body_efficiency = _clip01(total_body / total_range) if total_range > 0 else 0.0

    bodies = close - open_
    if direction > 0:
        aligned = (bodies > 0).sum()
    elif direction < 0:
        aligned = (bodies < 0).sum()
    else:
        aligned = 0
    directional_consistency = _clip01(float(aligned) / bars)

    candle_ranges = (high - low).replace(0, pd.NA)
    if direction > 0:
        locations = ((close - low) / candle_ranges).dropna()
    elif direction < 0:
        locations = ((high - close) / candle_ranges).dropna()
    else:
        locations = pd.Series(dtype=float)
    close_location = _clip01(float(locations.mean())) if not locations.empty else 0.0

    overlap_ratio = _overlap_ratio(window)
    trend_efficiency = _trend_efficiency(close)

    # D-grade experimental scaling. Keep it explicit so ablation tests can
    # remove/replace individual terms later.
    displacement_norm = _clip01(displacement_atr / 2.0)
    speed_norm = _clip01(speed_atr_per_bar / 0.25)

    if direction == 0:
        composite_score = 0.0
    else:
        composite_score = _clip01(
            0.25 * displacement_norm
            + 0.20 * speed_norm
            + 0.15 * body_efficiency
            + 0.15 * directional_consistency
            + 0.15 * close_location
            + 0.10 * (1.0 - overlap_ratio)
        )

    return StrengthSnapshot(
        direction=direction,
        composite_score=composite_score,
        displacement_atr=float(displacement_atr),
        speed_atr_per_bar=float(speed_atr_per_bar),
        body_efficiency=body_efficiency,
        directional_consistency=directional_consistency,
        close_location=close_location,
        overlap_ratio=overlap_ratio,
        trend_efficiency=trend_efficiency,
        atr=float(atr),
        bars=bars,
    )


def compare_strength(
    previous: StrengthSnapshot,
    current: StrengthSnapshot,
    min_delta: float = 0.10,
) -> StrengthTransition:
    """Describe whether the current push strengthened or weakened."""
    if min_delta < 0:
        raise ValueError("min_delta must be >= 0")

    direction_changed = previous.direction != current.direction
    delta = float(current.composite_score - previous.composite_score)

    if direction_changed:
        state = "DIRECTION_CHANGE"
    elif delta > min_delta:
        state = "STRENGTHENING"
    elif delta < -min_delta:
        state = "WEAKENING"
    else:
        state = "FLAT"

    return StrengthTransition(
        state=state,
        score_delta=delta,
        direction_changed=direction_changed,
        previous_score=float(previous.composite_score),
        current_score=float(current.composite_score),
    )
