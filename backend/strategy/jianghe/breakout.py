from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from strategy.jianghe.strength import calculate_directional_strength
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot

EVIDENCE_GRADE = "D_EXPERIMENTAL_QUANT_TRANSLATION"
SETUP_NAME = "BREAKOUT_CONTINUATION"
REQUIRED_COLUMNS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class BreakoutConfig:
    """Experimental S4 parameters; every numeric threshold must be backtested."""

    pressure_bars: int = 12
    breakout_window_bars: int = 2
    followthrough_bars: int = 3
    min_context_efficiency: float = 0.0
    min_tests: int = 2
    test_tolerance_atr: float = 0.40
    max_prebreak_close_breach_atr: float = 0.10
    max_approach_distance_atr: float = 0.80
    max_compression_ratio: float = 0.90
    require_compression: bool = True
    min_breakout_extension_atr: float = 0.10
    min_breakout_body_efficiency: float = 0.45
    min_breakout_close_location: float = 0.65
    min_breakout_strength: float = 0.40
    max_reentry_atr: float = 0.15
    min_hold_fraction: float = 1.0
    min_followthrough_extension_atr: float = 0.05
    min_followthrough_strength: float = 0.25
    invalidation_buffer_atr: float = 0.20
    evidence_grade: str = EVIDENCE_GRADE


@dataclass(frozen=True)
class BreakoutEvaluation:
    setup: str
    candidate: bool
    side: str | None
    regime: str
    context_efficiency: float
    level_type: str | None
    level_price: float | None
    atr: float | None
    test_count: int | None
    compression_ratio: float | None
    approach_distance_atr: float | None
    breakout_index: int | None
    breakout_extension_atr: float | None
    breakout_body_efficiency: float | None
    breakout_close_location: float | None
    breakout_strength: float | None
    hold_fraction: float | None
    final_extension_atr: float | None
    followthrough_strength: float | None
    entry_reference: float | None
    invalidation_reference: float | None
    gates: dict[str, bool]
    reason_codes: tuple[str, ...]
    failed_gates: tuple[str, ...]
    evidence_grade: str = EVIDENCE_GRADE

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_config(cfg: BreakoutConfig) -> None:
    if min(cfg.pressure_bars, cfg.breakout_window_bars, cfg.followthrough_bars) < 2:
        raise ValueError("pressure/breakout/followthrough windows must each contain >= 2 bars")
    if cfg.min_tests < 1:
        raise ValueError("min_tests must be >= 1")
    for value in (
        cfg.test_tolerance_atr,
        cfg.max_prebreak_close_breach_atr,
        cfg.max_approach_distance_atr,
        cfg.min_breakout_extension_atr,
        cfg.max_reentry_atr,
        cfg.min_followthrough_extension_atr,
        cfg.invalidation_buffer_atr,
    ):
        if value < 0:
            raise ValueError("ATR thresholds must be >= 0")
    if not 0 < cfg.max_compression_ratio <= 2:
        raise ValueError("max_compression_ratio must be in (0, 2]")
    for value in (
        cfg.min_breakout_body_efficiency,
        cfg.min_breakout_close_location,
        cfg.min_breakout_strength,
        cfg.min_hold_fraction,
        cfg.min_followthrough_strength,
    ):
        if not 0 <= value <= 1:
            raise ValueError("quality thresholds must be between 0 and 1")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")


def _true_range_series(df: pd.DataFrame) -> pd.Series:
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    return pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _mean_true_range(df: pd.DataFrame) -> float:
    value = float(_true_range_series(df).mean())
    return value if value > 0 else 1e-12


def _trend_side(structure: StructureSnapshot) -> tuple[int, str | None, str | None, float | None]:
    if structure.regime == MarketRegime.BULL_TREND:
        return 1, "LONG", "STRUCTURAL_RESISTANCE", structure.last_high_2
    if structure.regime == MarketRegime.BEAR_TREND:
        return -1, "SHORT", "STRUCTURAL_SUPPORT", structure.last_low_2
    return 0, None, None, None


def _empty_evaluation(
    structure: StructureSnapshot,
    side: str | None,
    level_type: str | None,
    level_price: float | None,
    entry_reference: float | None,
    reason: str,
) -> BreakoutEvaluation:
    return BreakoutEvaluation(
        setup=SETUP_NAME,
        candidate=False,
        side=side,
        regime=structure.regime.value,
        context_efficiency=float(structure.trend_efficiency),
        level_type=level_type,
        level_price=level_price,
        atr=None,
        test_count=None,
        compression_ratio=None,
        approach_distance_atr=None,
        breakout_index=None,
        breakout_extension_atr=None,
        breakout_body_efficiency=None,
        breakout_close_location=None,
        breakout_strength=None,
        hold_fraction=None,
        final_extension_atr=None,
        followthrough_strength=None,
        entry_reference=entry_reference,
        invalidation_reference=None,
        gates={"CONTEXT": False, "PRESSURE": False, "BREAKOUT": False, "HOLD": False},
        reason_codes=(reason,),
        failed_gates=("CONTEXT", "PRESSURE", "BREAKOUT", "HOLD"),
    )


def _compression_ratio(pressure: pd.DataFrame) -> float:
    tr = _true_range_series(pressure).astype(float).reset_index(drop=True)
    split = max(1, len(tr) // 2)
    early = float(tr.iloc[:split].mean())
    late = float(tr.iloc[split:].mean())
    if early <= 0:
        return 1.0
    return late / early


def _count_tests(pressure: pd.DataFrame, level: float, atr: float, direction: int, tolerance: float) -> int:
    threshold = tolerance * atr
    if direction > 0:
        distances = (level - pressure["high"].astype(float)).clip(lower=0.0)
    else:
        distances = (pressure["low"].astype(float) - level).clip(lower=0.0)
    return int((distances <= threshold).sum())


def _bar_quality(row: pd.Series, direction: int) -> tuple[float, float]:
    open_ = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    range_ = max(high - low, 1e-12)
    body_efficiency = abs(close - open_) / range_
    if direction > 0:
        close_location = (close - low) / range_
    else:
        close_location = (high - close) / range_
    return float(max(0.0, min(1.0, body_efficiency))), float(max(0.0, min(1.0, close_location)))


def evaluate_breakout_continuation_from_structure(
    structure: StructureSnapshot,
    execution_df: pd.DataFrame,
    config: BreakoutConfig | None = None,
) -> BreakoutEvaluation:
    """Evaluate a Jianghe-style breakout continuation candidate without trading.

    Four explicit gates are used:
      CONTEXT: higher-timeframe confirmed trend agrees with breakout direction;
      PRESSURE: repeated tests/approach into the structural level, preferably with compression;
      BREAKOUT: a directional close clears the level with acceptable bar/segment quality;
      HOLD: post-breakout bars remain accepted outside the level instead of failing back inside.

    Formulas and thresholds are an experimental quantitative translation, not a
    claim that Jianghe uses these exact private rules.
    """
    cfg = config or BreakoutConfig()
    _validate_config(cfg)
    _validate_ohlc(execution_df)

    direction, side, level_type, level_price = _trend_side(structure)
    entry_reference = float(execution_df["close"].iloc[-1]) if len(execution_df) else None
    if direction == 0 or level_price is None:
        return _empty_evaluation(
            structure, side, level_type, level_price, entry_reference, "CONTEXT_NOT_TRENDING"
        )

    required = cfg.pressure_bars + cfg.breakout_window_bars + cfg.followthrough_bars
    if len(execution_df) < required:
        return _empty_evaluation(
            structure, side, level_type, float(level_price), entry_reference, "INSUFFICIENT_EXECUTION_BARS"
        )

    window = execution_df.tail(required).reset_index(drop=True)
    p_end = cfg.pressure_bars
    b_end = p_end + cfg.breakout_window_bars
    pressure = window.iloc[:p_end]
    breakout_window = window.iloc[p_end:b_end]
    followthrough = window.iloc[b_end:]
    atr = _mean_true_range(window)
    level = float(level_price)

    context_ok = (
        structure.regime in {MarketRegime.BULL_TREND, MarketRegime.BEAR_TREND}
        and structure.trend_efficiency >= cfg.min_context_efficiency
    )

    test_count = _count_tests(pressure, level, atr, direction, cfg.test_tolerance_atr)
    compression_ratio = _compression_ratio(pressure)
    last_pressure_close = float(pressure["close"].iloc[-1])
    first_pressure_close = float(pressure["close"].iloc[0])
    approach_distance_atr = abs(level - last_pressure_close) / atr
    if direction > 0:
        approach_progress = last_pressure_close > first_pressure_close
        prebreak_clean = float(pressure["close"].max()) <= level + cfg.max_prebreak_close_breach_atr * atr
    else:
        approach_progress = last_pressure_close < first_pressure_close
        prebreak_clean = float(pressure["close"].min()) >= level - cfg.max_prebreak_close_breach_atr * atr
    compression_ok = compression_ratio <= cfg.max_compression_ratio if cfg.require_compression else True
    pressure_ok = (
        test_count >= cfg.min_tests
        and approach_distance_atr <= cfg.max_approach_distance_atr
        and approach_progress
        and prebreak_clean
        and compression_ok
    )

    breakout_index: int | None = None
    breakout_extension_atr: float | None = None
    breakout_body_efficiency: float | None = None
    breakout_close_location: float | None = None
    for local_index, (_, row) in enumerate(breakout_window.iterrows()):
        close = float(row["close"])
        extension = ((close - level) if direction > 0 else (level - close)) / atr
        if extension >= cfg.min_breakout_extension_atr:
            breakout_index = p_end + local_index
            breakout_extension_atr = float(extension)
            breakout_body_efficiency, breakout_close_location = _bar_quality(row, direction)
            break

    breakout_strength_snapshot = calculate_directional_strength(
        breakout_window, lookback=len(breakout_window)
    )
    breakout_direction_ok = breakout_strength_snapshot.direction == direction
    breakout_strength_ok = breakout_strength_snapshot.composite_score >= cfg.min_breakout_strength
    breakout_close_confirmed = breakout_index is not None
    breakout_bar_quality_ok = (
        breakout_close_confirmed
        and breakout_body_efficiency is not None
        and breakout_body_efficiency >= cfg.min_breakout_body_efficiency
        and breakout_close_location is not None
        and breakout_close_location >= cfg.min_breakout_close_location
    )
    breakout_ok = breakout_close_confirmed and breakout_direction_ok and breakout_strength_ok and breakout_bar_quality_ok

    follow_strength_snapshot = calculate_directional_strength(
        followthrough, lookback=len(followthrough)
    )
    follow_closes = followthrough["close"].astype(float)
    if direction > 0:
        accepted = follow_closes >= level - cfg.max_reentry_atr * atr
        final_extension_atr = (float(follow_closes.iloc[-1]) - level) / atr
        invalidation_reference = level - cfg.invalidation_buffer_atr * atr
    else:
        accepted = follow_closes <= level + cfg.max_reentry_atr * atr
        final_extension_atr = (level - float(follow_closes.iloc[-1])) / atr
        invalidation_reference = level + cfg.invalidation_buffer_atr * atr
    hold_fraction = float(accepted.mean())
    follow_direction_ok = follow_strength_snapshot.direction == direction
    follow_strength_ok = follow_strength_snapshot.composite_score >= cfg.min_followthrough_strength
    final_extension_ok = final_extension_atr >= cfg.min_followthrough_extension_atr
    hold_ok = (
        hold_fraction >= cfg.min_hold_fraction
        and final_extension_ok
        and follow_direction_ok
        and follow_strength_ok
    )

    gates = {
        "CONTEXT": bool(context_ok),
        "PRESSURE": bool(pressure_ok),
        "BREAKOUT": bool(breakout_ok),
        "HOLD": bool(hold_ok),
    }
    failed_gates = tuple(name for name, passed in gates.items() if not passed)

    reasons: list[str] = ["BULL_TREND_CONTEXT" if direction > 0 else "BEAR_TREND_CONTEXT"]
    if pressure_ok:
        reasons.extend(("REPEATED_LEVEL_TESTS", "PRESSURE_INTO_LEVEL"))
        if cfg.require_compression:
            reasons.append("RANGE_COMPRESSION")
    else:
        if test_count < cfg.min_tests:
            reasons.append("INSUFFICIENT_LEVEL_TESTS")
        if approach_distance_atr > cfg.max_approach_distance_atr:
            reasons.append("APPROACH_TOO_FAR_FROM_LEVEL")
        if not approach_progress:
            reasons.append("NO_DIRECTIONAL_APPROACH")
        if not prebreak_clean:
            reasons.append("LEVEL_ALREADY_BROKEN_BEFORE_BREAKOUT_WINDOW")
        if not compression_ok:
            reasons.append("NO_PREBREAK_COMPRESSION")

    if breakout_ok:
        reasons.extend(("BREAKOUT_CLOSE_CONFIRMED", "BREAKOUT_QUALITY_CONFIRMED"))
    else:
        if not breakout_close_confirmed:
            reasons.append("BREAKOUT_CLOSE_NOT_CONFIRMED")
        if not breakout_direction_ok:
            reasons.append("BREAKOUT_DIRECTION_NOT_ALIGNED")
        if not breakout_strength_ok:
            reasons.append("BREAKOUT_STRENGTH_TOO_LOW")
        if breakout_close_confirmed and not breakout_bar_quality_ok:
            reasons.append("BREAKOUT_BAR_QUALITY_TOO_LOW")

    if hold_ok:
        reasons.extend(("BREAKOUT_ACCEPTED_OUTSIDE_LEVEL", "FOLLOWTHROUGH_CONFIRMED"))
    else:
        if hold_fraction < cfg.min_hold_fraction:
            reasons.append("FAILED_BREAKOUT_REENTRY")
        if not final_extension_ok:
            reasons.append("NO_POST_BREAKOUT_EXTENSION")
        if not follow_direction_ok:
            reasons.append("FOLLOWTHROUGH_DIRECTION_NOT_ALIGNED")
        if not follow_strength_ok:
            reasons.append("FOLLOWTHROUGH_STRENGTH_TOO_LOW")

    return BreakoutEvaluation(
        setup=SETUP_NAME,
        candidate=all(gates.values()),
        side=side,
        regime=structure.regime.value,
        context_efficiency=float(structure.trend_efficiency),
        level_type=level_type,
        level_price=level,
        atr=float(atr),
        test_count=int(test_count),
        compression_ratio=float(compression_ratio),
        approach_distance_atr=float(approach_distance_atr),
        breakout_index=breakout_index,
        breakout_extension_atr=breakout_extension_atr,
        breakout_body_efficiency=breakout_body_efficiency,
        breakout_close_location=breakout_close_location,
        breakout_strength=float(breakout_strength_snapshot.composite_score),
        hold_fraction=float(hold_fraction),
        final_extension_atr=float(final_extension_atr),
        followthrough_strength=float(follow_strength_snapshot.composite_score),
        entry_reference=float(window["close"].iloc[-1]),
        invalidation_reference=float(invalidation_reference),
        gates=gates,
        reason_codes=tuple(reasons),
        failed_gates=failed_gates,
    )


def evaluate_breakout_continuation(
    context_df: pd.DataFrame,
    execution_df: pd.DataFrame,
    config: BreakoutConfig | None = None,
) -> BreakoutEvaluation:
    """Top-level S4 evaluator: higher-timeframe context + lower-timeframe breakout execution."""
    structure = classify_structure(context_df)
    return evaluate_breakout_continuation_from_structure(structure, execution_df, config)
