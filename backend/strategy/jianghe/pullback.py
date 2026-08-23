from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from strategy.jianghe.strength import calculate_directional_strength
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot

EVIDENCE_GRADE = "D_EXPERIMENTAL_QUANT_TRANSLATION"
SETUP_NAME = "TREND_PULLBACK_CONTINUATION"
REQUIRED_COLUMNS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class PullbackConfig:
    """Experimental S3 parameters; every numeric threshold must be backtested."""

    impulse_bars: int = 8
    pullback_bars: int = 5
    trigger_bars: int = 3
    min_context_efficiency: float = 0.0
    level_tolerance_atr: float = 0.75
    invalidation_buffer_atr: float = 0.20
    min_pullback_depth_atr: float = 0.30
    max_pullback_depth_atr: float = 4.00
    min_impulse_strength: float = 0.50
    max_pullback_to_impulse_ratio: float = 0.85
    min_trigger_strength: float = 0.45
    min_trigger_to_pullback_ratio: float = 0.75
    require_micro_reclaim: bool = True
    evidence_grade: str = EVIDENCE_GRADE


@dataclass(frozen=True)
class PullbackEvaluation:
    setup: str
    candidate: bool
    side: str | None
    regime: str
    context_efficiency: float
    level_type: str | None
    level_price: float | None
    level_distance_atr: float | None
    pullback_depth_atr: float | None
    entry_reference: float | None
    invalidation_reference: float | None
    impulse_strength: float | None
    pullback_strength: float | None
    trigger_strength: float | None
    gates: dict[str, bool]
    reason_codes: tuple[str, ...]
    failed_gates: tuple[str, ...]
    evidence_grade: str = EVIDENCE_GRADE

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_config(cfg: PullbackConfig) -> None:
    if min(cfg.impulse_bars, cfg.pullback_bars, cfg.trigger_bars) < 2:
        raise ValueError("impulse/pullback/trigger windows must each contain >= 2 bars")
    if cfg.level_tolerance_atr < 0 or cfg.invalidation_buffer_atr < 0:
        raise ValueError("ATR tolerances must be >= 0")
    if cfg.min_pullback_depth_atr < 0 or cfg.max_pullback_depth_atr < cfg.min_pullback_depth_atr:
        raise ValueError("invalid pullback depth bounds")
    if not 0 <= cfg.max_pullback_to_impulse_ratio <= 2:
        raise ValueError("max_pullback_to_impulse_ratio must be between 0 and 2")
    if not 0 <= cfg.min_trigger_to_pullback_ratio <= 2:
        raise ValueError("min_trigger_to_pullback_ratio must be between 0 and 2")


def _validate_ohlc(df: pd.DataFrame) -> None:
    missing = REQUIRED_COLUMNS.difference(df.columns)
    if missing:
        raise ValueError(f"missing OHLC columns: {sorted(missing)}")


def _mean_true_range(df: pd.DataFrame) -> float:
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
    value = float(tr.mean())
    return value if value > 0 else 1e-12


def _trend_side(structure: StructureSnapshot) -> tuple[int, str | None, str | None, float | None]:
    if structure.regime == MarketRegime.BULL_TREND:
        return 1, "LONG", "STRUCTURAL_SUPPORT", structure.last_low_2
    if structure.regime == MarketRegime.BEAR_TREND:
        return -1, "SHORT", "STRUCTURAL_RESISTANCE", structure.last_high_2
    return 0, None, None, None


def _distance_to_level_atr(df: pd.DataFrame, level: float, atr: float) -> float:
    distances = []
    for low, high in zip(df["low"].astype(float), df["high"].astype(float)):
        if low <= level <= high:
            distances.append(0.0)
        else:
            distances.append(min(abs(low - level), abs(high - level)))
    return float(min(distances) / atr) if distances else float("inf")


def _empty_evaluation(
    structure: StructureSnapshot,
    side: str | None,
    level_type: str | None,
    level_price: float | None,
    entry_reference: float | None,
    reason: str,
) -> PullbackEvaluation:
    return PullbackEvaluation(
        setup=SETUP_NAME,
        candidate=False,
        side=side,
        regime=structure.regime.value,
        context_efficiency=float(structure.trend_efficiency),
        level_type=level_type,
        level_price=level_price,
        level_distance_atr=None,
        pullback_depth_atr=None,
        entry_reference=entry_reference,
        invalidation_reference=None,
        impulse_strength=None,
        pullback_strength=None,
        trigger_strength=None,
        gates={"CONTEXT": False, "LEVEL": False, "STATE": False, "TRIGGER": False},
        reason_codes=(reason,),
        failed_gates=("CONTEXT", "LEVEL", "STATE", "TRIGGER"),
    )


def evaluate_trend_pullback_from_structure(
    structure: StructureSnapshot,
    execution_df: pd.DataFrame,
    config: PullbackConfig | None = None,
) -> PullbackEvaluation:
    """Evaluate a Jianghe-style trend-pullback candidate without placing an order.

    The four gates are intentionally explicit:
      CONTEXT: confirmed higher-timeframe trend;
      LEVEL: pullback reaches a structural level without invalidating it;
      STATE: prior impulse exists and the opposing pullback is weaker;
      TRIGGER: original trend direction re-accelerates and reclaims micro structure.

    The formulas and thresholds are an experimental quantitative translation,
    not a claim about Jianghe's private or exact rules.
    """
    cfg = config or PullbackConfig()
    _validate_config(cfg)
    _validate_ohlc(execution_df)

    trend_direction, side, level_type, level_price = _trend_side(structure)
    entry_reference = float(execution_df["close"].iloc[-1]) if len(execution_df) else None

    if trend_direction == 0 or level_price is None:
        return _empty_evaluation(
            structure, side, level_type, level_price, entry_reference, "CONTEXT_NOT_TRENDING"
        )

    required = cfg.impulse_bars + cfg.pullback_bars + cfg.trigger_bars
    if len(execution_df) < required:
        return _empty_evaluation(
            structure, side, level_type, float(level_price), entry_reference, "INSUFFICIENT_EXECUTION_BARS"
        )

    window = execution_df.tail(required).reset_index(drop=True)
    impulse = window.iloc[: cfg.impulse_bars]
    pullback_start = cfg.impulse_bars
    pullback_end = pullback_start + cfg.pullback_bars
    pullback = window.iloc[pullback_start:pullback_end]
    trigger = window.iloc[pullback_end:]

    atr = _mean_true_range(window)
    impulse_strength = calculate_directional_strength(impulse, lookback=len(impulse))
    pullback_strength = calculate_directional_strength(pullback, lookback=len(pullback))
    trigger_strength = calculate_directional_strength(trigger, lookback=len(trigger))

    context_ok = (
        structure.regime in {MarketRegime.BULL_TREND, MarketRegime.BEAR_TREND}
        and structure.trend_efficiency >= cfg.min_context_efficiency
    )

    level_distance_atr = _distance_to_level_atr(pullback, float(level_price), atr)
    if trend_direction > 0:
        pullback_extreme = float(pullback["low"].min())
        impulse_extreme = float(impulse["high"].max())
        invalidation_reference = float(level_price) - cfg.invalidation_buffer_atr * atr
        structure_intact = pullback_extreme >= invalidation_reference
        micro_reclaim = float(trigger["close"].iloc[-1]) > float(pullback["high"].iloc[-1])
        pullback_depth_atr = max(0.0, impulse_extreme - pullback_extreme) / atr
    else:
        pullback_extreme = float(pullback["high"].max())
        impulse_extreme = float(impulse["low"].min())
        invalidation_reference = float(level_price) + cfg.invalidation_buffer_atr * atr
        structure_intact = pullback_extreme <= invalidation_reference
        micro_reclaim = float(trigger["close"].iloc[-1]) < float(pullback["low"].iloc[-1])
        pullback_depth_atr = max(0.0, pullback_extreme - impulse_extreme) / atr

    level_ok = (
        level_distance_atr <= cfg.level_tolerance_atr
        and structure_intact
    )

    impulse_ok = (
        impulse_strength.direction == trend_direction
        and impulse_strength.composite_score >= cfg.min_impulse_strength
    )
    opposing_pullback = pullback_strength.direction == -trend_direction
    pullback_weaker = (
        pullback_strength.composite_score
        <= impulse_strength.composite_score * cfg.max_pullback_to_impulse_ratio
    )
    depth_ok = cfg.min_pullback_depth_atr <= pullback_depth_atr <= cfg.max_pullback_depth_atr
    state_ok = impulse_ok and opposing_pullback and pullback_weaker and depth_ok

    trigger_direction_ok = trigger_strength.direction == trend_direction
    trigger_absolute_ok = trigger_strength.composite_score >= cfg.min_trigger_strength
    trigger_relative_ok = (
        trigger_strength.composite_score
        >= pullback_strength.composite_score * cfg.min_trigger_to_pullback_ratio
    )
    trigger_structure_ok = micro_reclaim if cfg.require_micro_reclaim else True
    trigger_ok = trigger_direction_ok and trigger_absolute_ok and trigger_relative_ok and trigger_structure_ok

    gates = {
        "CONTEXT": bool(context_ok),
        "LEVEL": bool(level_ok),
        "STATE": bool(state_ok),
        "TRIGGER": bool(trigger_ok),
    }
    failed_gates = tuple(name for name, passed in gates.items() if not passed)

    reason_codes: list[str] = []
    reason_codes.append("BULL_TREND_CONTEXT" if trend_direction > 0 else "BEAR_TREND_CONTEXT")
    if level_ok:
        reason_codes.append("AT_STRUCTURAL_LEVEL")
    else:
        if level_distance_atr > cfg.level_tolerance_atr:
            reason_codes.append("STRUCTURAL_LEVEL_TOO_FAR")
        if not structure_intact:
            reason_codes.append("STRUCTURAL_LEVEL_INVALIDATED")
    if state_ok:
        reason_codes.append("OPPOSING_PULLBACK_WEAKER_THAN_IMPULSE")
    else:
        if not impulse_ok:
            reason_codes.append("PRIOR_IMPULSE_NOT_CONFIRMED")
        if not opposing_pullback:
            reason_codes.append("PULLBACK_DIRECTION_NOT_OPPOSING")
        if not pullback_weaker:
            reason_codes.append("PULLBACK_NOT_WEAKER_THAN_IMPULSE")
        if not depth_ok:
            reason_codes.append("PULLBACK_DEPTH_OUT_OF_RANGE")
    if trigger_ok:
        reason_codes.extend(("TREND_DIRECTION_REACCELERATION", "MICRO_STRUCTURE_RECLAIM"))
    else:
        if not trigger_direction_ok:
            reason_codes.append("TRIGGER_DIRECTION_NOT_RESUMED")
        if not trigger_absolute_ok:
            reason_codes.append("TRIGGER_STRENGTH_TOO_LOW")
        if not trigger_relative_ok:
            reason_codes.append("TRIGGER_WEAK_RELATIVE_TO_PULLBACK")
        if not trigger_structure_ok:
            reason_codes.append("MICRO_STRUCTURE_NOT_RECLAIMED")

    return PullbackEvaluation(
        setup=SETUP_NAME,
        candidate=all(gates.values()),
        side=side,
        regime=structure.regime.value,
        context_efficiency=float(structure.trend_efficiency),
        level_type=level_type,
        level_price=float(level_price),
        level_distance_atr=float(level_distance_atr),
        pullback_depth_atr=float(pullback_depth_atr),
        entry_reference=float(window["close"].iloc[-1]),
        invalidation_reference=float(invalidation_reference),
        impulse_strength=float(impulse_strength.composite_score),
        pullback_strength=float(pullback_strength.composite_score),
        trigger_strength=float(trigger_strength.composite_score),
        gates=gates,
        reason_codes=tuple(reason_codes),
        failed_gates=failed_gates,
    )


def evaluate_trend_pullback(
    context_df: pd.DataFrame,
    execution_df: pd.DataFrame,
    config: PullbackConfig | None = None,
) -> PullbackEvaluation:
    """Top-level S3 evaluator: higher-timeframe context + lower-timeframe execution."""
    structure = classify_structure(context_df)
    return evaluate_trend_pullback_from_structure(structure, execution_df, config)
