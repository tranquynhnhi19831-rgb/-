from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from strategy.jianghe.strength import calculate_directional_strength
from strategy.jianghe.structure import classify_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot

EVIDENCE_GRADE = "D_EXPERIMENTAL_QUANT_TRANSLATION"
SETUP_NAME = "SECOND_PUSH_FAILURE"
REQUIRED_COLUMNS = {"open", "high", "low", "close"}


@dataclass(frozen=True)
class SecondPushConfig:
    """Experimental S5 parameters; all numeric thresholds require backtesting."""

    push1_bars: int = 6
    reset_bars: int = 4
    push2_bars: int = 6
    trigger_bars: int = 3
    allow_range_context: bool = True
    level_tolerance_atr: float = 0.80
    min_reset_depth_atr: float = 0.35
    max_reset_depth_atr: float = 5.00
    min_push1_strength: float = 0.45
    max_push2_to_push1_strength_ratio: float = 0.82
    max_push2_to_push1_displacement_ratio: float = 0.90
    max_push2_to_push1_speed_ratio: float = 0.90
    max_push2_result_extension_atr: float = 0.20
    acceptance_breach_atr: float = 0.10
    max_acceptance_fraction: float = 0.34
    min_trigger_strength: float = 0.40
    min_trigger_to_push2_ratio: float = 0.75
    require_micro_break: bool = True
    invalidation_buffer_atr: float = 0.20
    evidence_grade: str = EVIDENCE_GRADE


@dataclass(frozen=True)
class SecondPushEvaluation:
    setup: str
    candidate: bool
    signal_state: str
    weakness_detected: bool
    side: str | None
    push_direction: str | None
    regime: str
    level_type: str | None
    level_price: float | None
    atr: float | None
    push1_distance_atr: float | None
    push2_distance_atr: float | None
    reset_depth_atr: float | None
    push1_strength: float | None
    push2_strength: float | None
    strength_ratio: float | None
    displacement_ratio: float | None
    speed_ratio: float | None
    result_extension_atr: float | None
    acceptance_fraction: float | None
    trigger_strength: float | None
    entry_reference: float | None
    invalidation_reference: float | None
    gates: dict[str, bool]
    reason_codes: tuple[str, ...]
    failed_gates: tuple[str, ...]
    evidence_grade: str = EVIDENCE_GRADE

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_config(cfg: SecondPushConfig) -> None:
    if min(cfg.push1_bars, cfg.reset_bars, cfg.push2_bars, cfg.trigger_bars) < 2:
        raise ValueError("push/reset/trigger windows must each contain >= 2 bars")
    for value in (
        cfg.level_tolerance_atr,
        cfg.min_reset_depth_atr,
        cfg.max_reset_depth_atr,
        cfg.max_push2_result_extension_atr,
        cfg.acceptance_breach_atr,
        cfg.invalidation_buffer_atr,
    ):
        if value < 0:
            raise ValueError("ATR thresholds must be >= 0")
    if cfg.max_reset_depth_atr < cfg.min_reset_depth_atr:
        raise ValueError("max_reset_depth_atr must be >= min_reset_depth_atr")
    for value in (
        cfg.min_push1_strength,
        cfg.max_push2_to_push1_strength_ratio,
        cfg.max_push2_to_push1_displacement_ratio,
        cfg.max_push2_to_push1_speed_ratio,
        cfg.max_acceptance_fraction,
        cfg.min_trigger_strength,
        cfg.min_trigger_to_push2_ratio,
    ):
        if not 0 <= value <= 2:
            raise ValueError("strength/ratio thresholds must be between 0 and 2")


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


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 1e-12:
        return float("inf") if numerator > 1e-12 else 0.0
    return float(numerator / denominator)


def _level_for_direction(
    structure: StructureSnapshot,
    direction: int,
) -> tuple[str | None, float | None]:
    if direction > 0:
        return "STRUCTURAL_RESISTANCE", structure.last_high_2
    if direction < 0:
        return "STRUCTURAL_SUPPORT", structure.last_low_2
    return None, None


def _distance_to_level_atr(df: pd.DataFrame, level: float, atr: float, direction: int) -> float:
    if direction > 0:
        extreme = float(df["high"].astype(float).max())
    else:
        extreme = float(df["low"].astype(float).min())
    return abs(extreme - level) / atr


def _empty_evaluation(
    structure: StructureSnapshot,
    entry_reference: float | None,
    reason: str,
) -> SecondPushEvaluation:
    return SecondPushEvaluation(
        setup=SETUP_NAME,
        candidate=False,
        signal_state="NO_SETUP",
        weakness_detected=False,
        side=None,
        push_direction=None,
        regime=structure.regime.value,
        level_type=None,
        level_price=None,
        atr=None,
        push1_distance_atr=None,
        push2_distance_atr=None,
        reset_depth_atr=None,
        push1_strength=None,
        push2_strength=None,
        strength_ratio=None,
        displacement_ratio=None,
        speed_ratio=None,
        result_extension_atr=None,
        acceptance_fraction=None,
        trigger_strength=None,
        entry_reference=entry_reference,
        invalidation_reference=None,
        gates={"CONTEXT": False, "LOCATION": False, "FAILURE": False, "TRIGGER": False},
        reason_codes=(reason,),
        failed_gates=("CONTEXT", "LOCATION", "FAILURE", "TRIGGER"),
    )


def evaluate_second_push_failure_from_structure(
    structure: StructureSnapshot,
    execution_df: pd.DataFrame,
    config: SecondPushConfig | None = None,
) -> SecondPushEvaluation:
    """Evaluate a two-push exhaustion/reversal candidate without placing an order.

    The setup intentionally separates *weakness* from a tradable reversal candidate:
      CONTEXT: a valid higher-timeframe structural level exists;
      LOCATION: two same-direction pushes test the same level with a reset between them;
      FAILURE: push #2 produces materially worse effort/result and is not accepted beyond the level;
      TRIGGER: the opposite side takes control and breaks micro structure.

    A failed TRIGGER can still return `signal_state=SECOND_PUSH_WEAKNESS`; this is
    observational information only and must not be treated as an order signal.
    """
    cfg = config or SecondPushConfig()
    _validate_config(cfg)
    _validate_ohlc(execution_df)

    entry_reference = float(execution_df["close"].iloc[-1]) if len(execution_df) else None
    context_allowed = structure.regime != MarketRegime.UNKNOWN and (
        cfg.allow_range_context or structure.regime != MarketRegime.RANGE
    )
    if not context_allowed:
        return _empty_evaluation(structure, entry_reference, "CONTEXT_NOT_SUPPORTED")

    required = cfg.push1_bars + cfg.reset_bars + cfg.push2_bars + cfg.trigger_bars
    if len(execution_df) < required:
        return _empty_evaluation(structure, entry_reference, "INSUFFICIENT_EXECUTION_BARS")

    window = execution_df.tail(required).reset_index(drop=True)
    p1_end = cfg.push1_bars
    reset_end = p1_end + cfg.reset_bars
    p2_end = reset_end + cfg.push2_bars
    push1 = window.iloc[:p1_end]
    reset = window.iloc[p1_end:reset_end]
    push2 = window.iloc[reset_end:p2_end]
    trigger = window.iloc[p2_end:]

    atr = _mean_true_range(window)
    push1_strength = calculate_directional_strength(push1, lookback=len(push1))
    reset_strength = calculate_directional_strength(reset, lookback=len(reset))
    push2_strength = calculate_directional_strength(push2, lookback=len(push2))
    trigger_strength = calculate_directional_strength(trigger, lookback=len(trigger))

    push_direction = push1_strength.direction
    level_type, level_price = _level_for_direction(structure, push_direction)
    if push_direction == 0 or level_price is None:
        return _empty_evaluation(structure, entry_reference, "NO_VALID_PUSH_DIRECTION_OR_LEVEL")

    level = float(level_price)
    side = "SHORT" if push_direction > 0 else "LONG"
    direction_name = "UP" if push_direction > 0 else "DOWN"

    context_ok = context_allowed and level_price is not None

    push1_distance_atr = _distance_to_level_atr(push1, level, atr, push_direction)
    push2_distance_atr = _distance_to_level_atr(push2, level, atr, push_direction)
    if push_direction > 0:
        reset_depth_atr = max(0.0, level - float(reset["low"].min())) / atr
        push1_extreme = float(push1["high"].max())
        push2_extreme = float(push2["high"].max())
        result_extension_atr = (push2_extreme - push1_extreme) / atr
        accepted = push2["close"].astype(float) > level + cfg.acceptance_breach_atr * atr
        invalidation_reference = max(push1_extreme, push2_extreme) + cfg.invalidation_buffer_atr * atr
        micro_break = float(trigger["close"].iloc[-1]) < float(push2["low"].iloc[-1])
    else:
        reset_depth_atr = max(0.0, float(reset["high"].max()) - level) / atr
        push1_extreme = float(push1["low"].min())
        push2_extreme = float(push2["low"].min())
        result_extension_atr = (push1_extreme - push2_extreme) / atr
        accepted = push2["close"].astype(float) < level - cfg.acceptance_breach_atr * atr
        invalidation_reference = min(push1_extreme, push2_extreme) - cfg.invalidation_buffer_atr * atr
        micro_break = float(trigger["close"].iloc[-1]) > float(push2["high"].iloc[-1])

    reset_direction_ok = reset_strength.direction in {0, -push_direction}
    reset_depth_ok = cfg.min_reset_depth_atr <= reset_depth_atr <= cfg.max_reset_depth_atr
    location_ok = (
        push1_distance_atr <= cfg.level_tolerance_atr
        and push2_distance_atr <= cfg.level_tolerance_atr
        and reset_direction_ok
        and reset_depth_ok
        and push2_strength.direction == push_direction
    )

    strength_ratio = _safe_ratio(push2_strength.composite_score, push1_strength.composite_score)
    displacement_ratio = _safe_ratio(push2_strength.displacement_atr, push1_strength.displacement_atr)
    speed_ratio = _safe_ratio(push2_strength.speed_atr_per_bar, push1_strength.speed_atr_per_bar)
    acceptance_fraction = float(accepted.mean())

    push1_quality_ok = push1_strength.composite_score >= cfg.min_push1_strength
    second_push_strength_weaker = strength_ratio <= cfg.max_push2_to_push1_strength_ratio
    second_push_displacement_weaker = displacement_ratio <= cfg.max_push2_to_push1_displacement_ratio
    second_push_speed_weaker = speed_ratio <= cfg.max_push2_to_push1_speed_ratio
    result_not_improved = result_extension_atr <= cfg.max_push2_result_extension_atr
    no_acceptance = acceptance_fraction <= cfg.max_acceptance_fraction
    failure_ok = (
        push1_quality_ok
        and second_push_strength_weaker
        and second_push_displacement_weaker
        and second_push_speed_weaker
        and result_not_improved
        and no_acceptance
    )

    trigger_direction_ok = trigger_strength.direction == -push_direction
    trigger_absolute_ok = trigger_strength.composite_score >= cfg.min_trigger_strength
    trigger_relative_ok = (
        trigger_strength.composite_score
        >= push2_strength.composite_score * cfg.min_trigger_to_push2_ratio
    )
    trigger_structure_ok = micro_break if cfg.require_micro_break else True
    trigger_ok = trigger_direction_ok and trigger_absolute_ok and trigger_relative_ok and trigger_structure_ok

    gates = {
        "CONTEXT": bool(context_ok),
        "LOCATION": bool(location_ok),
        "FAILURE": bool(failure_ok),
        "TRIGGER": bool(trigger_ok),
    }
    failed_gates = tuple(name for name, passed in gates.items() if not passed)
    weakness_detected = bool(context_ok and location_ok and failure_ok)
    candidate = bool(weakness_detected and trigger_ok)
    signal_state = (
        "REVERSAL_CANDIDATE"
        if candidate
        else "SECOND_PUSH_WEAKNESS"
        if weakness_detected
        else "NO_SETUP"
    )

    reasons: list[str] = []
    if structure.regime == MarketRegime.RANGE:
        reasons.append("RANGE_BOUNDARY_CONTEXT")
    else:
        reasons.append(f"{structure.regime.value}_CONTEXT")

    if location_ok:
        reasons.extend(("TWO_PUSHES_SAME_LEVEL", "RESET_BETWEEN_PUSHES"))
    else:
        if push1_distance_atr > cfg.level_tolerance_atr:
            reasons.append("PUSH1_NOT_AT_LEVEL")
        if push2_distance_atr > cfg.level_tolerance_atr:
            reasons.append("PUSH2_NOT_AT_LEVEL")
        if not reset_direction_ok:
            reasons.append("RESET_NOT_OPPOSING")
        if not reset_depth_ok:
            reasons.append("RESET_DEPTH_OUT_OF_RANGE")
        if push2_strength.direction != push_direction:
            reasons.append("PUSH2_DIRECTION_NOT_MATCHED")

    if failure_ok:
        reasons.extend(("SECOND_PUSH_WEAKER", "EFFORT_RESULT_DETERIORATION", "NO_ACCEPTED_BREAKOUT"))
    else:
        if not push1_quality_ok:
            reasons.append("PUSH1_STRENGTH_TOO_LOW")
        if not second_push_strength_weaker:
            reasons.append("SECOND_PUSH_NOT_WEAKER_BY_SCORE")
        if not second_push_displacement_weaker:
            reasons.append("SECOND_PUSH_DISPLACEMENT_NOT_WEAKER")
        if not second_push_speed_weaker:
            reasons.append("SECOND_PUSH_SPEED_NOT_WEAKER")
        if not result_not_improved:
            reasons.append("SECOND_PUSH_RESULT_EXTENDED_TOO_FAR")
        if not no_acceptance:
            reasons.append("SECOND_PUSH_ACCEPTED_BEYOND_LEVEL")

    if trigger_ok:
        reasons.extend(("OPPOSITE_SIDE_TAKES_CONTROL", "MICRO_STRUCTURE_BREAK"))
    else:
        if not trigger_direction_ok:
            reasons.append("OPPOSITE_TRIGGER_DIRECTION_MISSING")
        if not trigger_absolute_ok:
            reasons.append("OPPOSITE_TRIGGER_STRENGTH_TOO_LOW")
        if not trigger_relative_ok:
            reasons.append("OPPOSITE_TRIGGER_WEAK_RELATIVE_TO_PUSH2")
        if not trigger_structure_ok:
            reasons.append("MICRO_STRUCTURE_NOT_BROKEN")

    return SecondPushEvaluation(
        setup=SETUP_NAME,
        candidate=candidate,
        signal_state=signal_state,
        weakness_detected=weakness_detected,
        side=side,
        push_direction=direction_name,
        regime=structure.regime.value,
        level_type=level_type,
        level_price=level,
        atr=float(atr),
        push1_distance_atr=float(push1_distance_atr),
        push2_distance_atr=float(push2_distance_atr),
        reset_depth_atr=float(reset_depth_atr),
        push1_strength=float(push1_strength.composite_score),
        push2_strength=float(push2_strength.composite_score),
        strength_ratio=float(strength_ratio),
        displacement_ratio=float(displacement_ratio),
        speed_ratio=float(speed_ratio),
        result_extension_atr=float(result_extension_atr),
        acceptance_fraction=float(acceptance_fraction),
        trigger_strength=float(trigger_strength.composite_score),
        entry_reference=float(window["close"].iloc[-1]),
        invalidation_reference=float(invalidation_reference),
        gates=gates,
        reason_codes=tuple(reasons),
        failed_gates=failed_gates,
    )


def evaluate_second_push_failure(
    context_df: pd.DataFrame,
    execution_df: pd.DataFrame,
    config: SecondPushConfig | None = None,
) -> SecondPushEvaluation:
    """Top-level S5 evaluator: higher-timeframe structure + lower-timeframe two-push sequence."""
    structure = classify_structure(context_df)
    return evaluate_second_push_failure_from_structure(structure, execution_df, config)
