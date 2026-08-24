from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from strategy.jianghe.strength import calculate_directional_strength
from strategy.jianghe.structure import find_confirmed_swings
from strategy.jianghe.types import MarketRegime, StructureSnapshot, SwingPoint

SETUP_NAME = "TREND_PULLBACK_EVENT_V3"
EVIDENCE_GRADE = "D_EXPERIMENTAL_EVENT_TRANSLATION"
REQUIRED_COLUMNS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class EventPullbackConfig:
    """Research-only event-driven pullback profile.

    Unlike the V1/V2 fixed 8+5+3 segmentation, this profile derives impulse,
    pullback and trigger phases from confirmed lower-timeframe swing events.
    Numeric thresholds remain experimental and require out-of-sample testing.
    """

    swing_left: int = 2
    swing_right: int = 2
    min_context_efficiency: float = 0.22
    level_tolerance_atr: float = 0.75
    invalidation_buffer_atr: float = 0.20
    min_impulse_bars: int = 3
    max_impulse_bars: int = 24
    min_pullback_bars: int = 2
    max_pullback_bars: int = 16
    min_trigger_bars: int = 2
    max_trigger_bars: int = 10
    min_impulse_strength: float = 0.52
    max_pullback_to_impulse_ratio: float = 0.78
    min_trigger_strength: float = 0.42
    min_trigger_to_pullback_ratio: float = 0.90
    evidence_grade: str = EVIDENCE_GRADE


@dataclass(frozen=True)
class EventPullbackEvaluation:
    setup: str
    candidate: bool
    side: str | None
    regime: str
    context_efficiency: float
    level_type: str | None
    level_price: float | None
    atr: float | None
    impulse_start_index: int | None
    impulse_end_index: int | None
    pullback_end_index: int | None
    impulse_bars: int | None
    pullback_bars: int | None
    trigger_bars: int | None
    level_distance_atr: float | None
    impulse_strength: float | None
    pullback_strength: float | None
    trigger_strength: float | None
    entry_reference: float | None
    invalidation_reference: float | None
    gates: dict[str, bool]
    reason_codes: tuple[str, ...]
    evidence_grade: str = EVIDENCE_GRADE

    def to_dict(self) -> dict:
        return asdict(self)


def _validate(df: pd.DataFrame, cfg: EventPullbackConfig) -> None:
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")
    if min(cfg.swing_left, cfg.swing_right) < 1:
        raise ValueError("swing_left/right must be >= 1")
    if min(cfg.min_impulse_bars, cfg.min_pullback_bars, cfg.min_trigger_bars) < 2:
        raise ValueError("minimum phase lengths must be >= 2 bars")
    if cfg.max_impulse_bars < cfg.min_impulse_bars:
        raise ValueError("invalid impulse length bounds")
    if cfg.max_pullback_bars < cfg.min_pullback_bars:
        raise ValueError("invalid pullback length bounds")
    if cfg.max_trigger_bars < cfg.min_trigger_bars:
        raise ValueError("invalid trigger length bounds")


def _atr(df: pd.DataFrame) -> float:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    value = float(tr.mean())
    return value if value > 0 else 1e-12


def _latest_bull_sequence(highs: list[SwingPoint], lows: list[SwingPoint]):
    """Return latest confirmed L0 -> H1 -> L2 sequence."""
    for l2 in reversed(lows):
        prior_highs = [h for h in highs if h.index < l2.index]
        if not prior_highs:
            continue
        h1 = prior_highs[-1]
        prior_lows = [l for l in lows if l.index < h1.index]
        if prior_lows:
            return prior_lows[-1], h1, l2
    return None


def _latest_bear_sequence(highs: list[SwingPoint], lows: list[SwingPoint]):
    """Return latest confirmed H0 -> L1 -> H2 sequence."""
    for h2 in reversed(highs):
        prior_lows = [l for l in lows if l.index < h2.index]
        if not prior_lows:
            continue
        l1 = prior_lows[-1]
        prior_highs = [h for h in highs if h.index < l1.index]
        if prior_highs:
            return prior_highs[-1], l1, h2
    return None


def _empty(structure: StructureSnapshot, reason: str) -> EventPullbackEvaluation:
    return EventPullbackEvaluation(
        setup=SETUP_NAME,
        candidate=False,
        side=None,
        regime=structure.regime.value,
        context_efficiency=float(structure.trend_efficiency),
        level_type=None,
        level_price=None,
        atr=None,
        impulse_start_index=None,
        impulse_end_index=None,
        pullback_end_index=None,
        impulse_bars=None,
        pullback_bars=None,
        trigger_bars=None,
        level_distance_atr=None,
        impulse_strength=None,
        pullback_strength=None,
        trigger_strength=None,
        entry_reference=None,
        invalidation_reference=None,
        gates={"CONTEXT": False, "EVENTS": False, "LEVEL": False, "MOMENTUM": False, "TRIGGER": False},
        reason_codes=(reason,),
    )


def evaluate_event_pullback_from_structure(
    structure: StructureSnapshot,
    execution_df: pd.DataFrame,
    config: EventPullbackConfig | None = None,
) -> EventPullbackEvaluation:
    cfg = config or EventPullbackConfig()
    _validate(execution_df, cfg)

    if structure.regime == MarketRegime.BULL_TREND:
        direction, side = 1, "LONG"
        level_type, level_price = "STRUCTURAL_SUPPORT", structure.last_low_2
    elif structure.regime == MarketRegime.BEAR_TREND:
        direction, side = -1, "SHORT"
        level_type, level_price = "STRUCTURAL_RESISTANCE", structure.last_high_2
    else:
        return _empty(structure, "CONTEXT_NOT_TRENDING")

    if level_price is None:
        return _empty(structure, "STRUCTURAL_LEVEL_MISSING")
    if structure.trend_efficiency < cfg.min_context_efficiency:
        return _empty(structure, "CONTEXT_EFFICIENCY_TOO_LOW")
    if structure.net_direction != direction:
        return _empty(structure, "CONTEXT_DIRECTION_NOT_ALIGNED")

    df = execution_df.reset_index(drop=True).copy()
    min_required = 2 * (cfg.swing_left + cfg.swing_right) + cfg.min_trigger_bars + 3
    if len(df) < min_required:
        return _empty(structure, "INSUFFICIENT_EXECUTION_BARS")

    highs, lows = find_confirmed_swings(df, cfg.swing_left, cfg.swing_right)
    sequence = _latest_bull_sequence(highs, lows) if direction > 0 else _latest_bear_sequence(highs, lows)
    if sequence is None:
        return _empty(structure, "NO_CONFIRMED_IMPULSE_PULLBACK_SEQUENCE")

    p0, p1, p2 = sequence
    impulse_start = int(p0.index)
    impulse_end = int(p1.index)
    pullback_end = int(p2.index)

    # Pivot bars belong to the leg that terminates at them. The next leg starts
    # on the following bar. This avoids double-counting the large terminal
    # impulse candle as part of the pullback and the pullback pivot as part of
    # the re-acceleration segment.
    impulse_bars = impulse_end - impulse_start + 1
    pullback_bars = pullback_end - impulse_end
    trigger_bars = len(df) - pullback_end - 1

    phase_lengths_ok = (
        cfg.min_impulse_bars <= impulse_bars <= cfg.max_impulse_bars
        and cfg.min_pullback_bars <= pullback_bars <= cfg.max_pullback_bars
        and cfg.min_trigger_bars <= trigger_bars <= cfg.max_trigger_bars
    )
    if not phase_lengths_ok:
        result = _empty(structure, "EVENT_PHASE_LENGTH_OUT_OF_RANGE")
        return EventPullbackEvaluation(
            **{
                **result.to_dict(),
                "side": side,
                "level_type": level_type,
                "level_price": float(level_price),
                "impulse_start_index": impulse_start,
                "impulse_end_index": impulse_end,
                "pullback_end_index": pullback_end,
                "impulse_bars": impulse_bars,
                "pullback_bars": pullback_bars,
                "trigger_bars": trigger_bars,
            }
        )

    impulse = df.iloc[impulse_start : impulse_end + 1]
    pullback = df.iloc[impulse_end + 1 : pullback_end + 1]
    trigger = df.iloc[pullback_end + 1 :]
    local_window = df.iloc[impulse_start:]
    atr = _atr(local_window)

    impulse_strength = calculate_directional_strength(impulse, lookback=len(impulse))
    pullback_strength = calculate_directional_strength(pullback, lookback=len(pullback))
    trigger_strength = calculate_directional_strength(trigger, lookback=len(trigger))

    level = float(level_price)
    pullback_extreme = float(p2.price)
    level_distance_atr = abs(pullback_extreme - level) / atr
    if direction > 0:
        structure_intact = pullback_extreme >= level - cfg.invalidation_buffer_atr * atr
        invalidation = pullback_extreme - cfg.invalidation_buffer_atr * atr
        previous_trigger_high = float(trigger["high"].iloc[:-1].max())
        micro_reclaim = float(trigger["close"].iloc[-1]) > previous_trigger_high
    else:
        structure_intact = pullback_extreme <= level + cfg.invalidation_buffer_atr * atr
        invalidation = pullback_extreme + cfg.invalidation_buffer_atr * atr
        previous_trigger_low = float(trigger["low"].iloc[:-1].min())
        micro_reclaim = float(trigger["close"].iloc[-1]) < previous_trigger_low

    level_ok = level_distance_atr <= cfg.level_tolerance_atr and structure_intact
    impulse_ok = impulse_strength.direction == direction and impulse_strength.composite_score >= cfg.min_impulse_strength
    pullback_opposes = pullback_strength.direction in {0, -direction}
    pullback_weaker = pullback_strength.composite_score <= impulse_strength.composite_score * cfg.max_pullback_to_impulse_ratio
    momentum_ok = impulse_ok and pullback_opposes and pullback_weaker
    trigger_ok = (
        trigger_strength.direction == direction
        and trigger_strength.composite_score >= cfg.min_trigger_strength
        and trigger_strength.composite_score >= pullback_strength.composite_score * cfg.min_trigger_to_pullback_ratio
        and micro_reclaim
    )

    gates = {
        "CONTEXT": True,
        "EVENTS": True,
        "LEVEL": bool(level_ok),
        "MOMENTUM": bool(momentum_ok),
        "TRIGGER": bool(trigger_ok),
    }
    reasons = ["EVENT_DRIVEN_PHASES", "BULL_TREND_CONTEXT" if direction > 0 else "BEAR_TREND_CONTEXT"]
    if level_ok:
        reasons.append("PULLBACK_SWING_AT_STRUCTURAL_LEVEL")
    if momentum_ok:
        reasons.append("PULLBACK_WEAKER_THAN_IMPULSE")
    if trigger_ok:
        reasons.extend(("TREND_REACCELERATION", "POST_PULLBACK_MICRO_RECLAIM"))

    return EventPullbackEvaluation(
        setup=SETUP_NAME,
        candidate=all(gates.values()),
        side=side,
        regime=structure.regime.value,
        context_efficiency=float(structure.trend_efficiency),
        level_type=level_type,
        level_price=level,
        atr=float(atr),
        impulse_start_index=impulse_start,
        impulse_end_index=impulse_end,
        pullback_end_index=pullback_end,
        impulse_bars=impulse_bars,
        pullback_bars=pullback_bars,
        trigger_bars=trigger_bars,
        level_distance_atr=float(level_distance_atr),
        impulse_strength=float(impulse_strength.composite_score),
        pullback_strength=float(pullback_strength.composite_score),
        trigger_strength=float(trigger_strength.composite_score),
        entry_reference=float(df["close"].iloc[-1]),
        invalidation_reference=float(invalidation),
        gates=gates,
        reason_codes=tuple(reasons),
    )
