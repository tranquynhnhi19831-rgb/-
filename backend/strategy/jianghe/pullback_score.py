from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategy.jianghe.pullback_event import EventPullbackConfig, EventPullbackEvaluation
from strategy.jianghe.strength import calculate_directional_strength


@dataclass(frozen=True)
class ScoredPullbackDecision:
    eligible: bool
    quality_score: float
    hard_gates: dict[str, bool]
    components: dict[str, float]
    reason_codes: tuple[str, ...]


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def score_event_pullback(
    evaluation: EventPullbackEvaluation,
    execution_df: pd.DataFrame,
    config: EventPullbackConfig | None = None,
    min_quality_score: float = 0.55,
) -> ScoredPullbackDecision:
    """Turn valid Jianghe structure into a graded quality decision.

    V2/V3 used several momentum thresholds as simultaneous hard gates. The Q1
    diagnostics showed that this can collapse the sample to only a handful of
    trades without fixing expectancy. V5 keeps structural facts as hard gates
    (trend context, confirmed event sequence, key-location integrity, correct
    phase directions and actual micro reclaim) and treats *how strong* those
    phases are as a score.

    Equal component weights are deliberate: this is a coarse research model,
    not a fitted parameter surface. The score is also suitable for selecting the
    best simultaneous candidate across the seven-symbol universe.
    """
    cfg = config or EventPullbackConfig()
    if not 0.0 <= min_quality_score <= 1.0:
        raise ValueError("min_quality_score must be between 0 and 1")

    required = (
        evaluation.impulse_start_index,
        evaluation.impulse_end_index,
        evaluation.pullback_end_index,
        evaluation.level_distance_atr,
        evaluation.impulse_strength,
        evaluation.pullback_strength,
        evaluation.trigger_strength,
    )
    if any(value is None for value in required) or evaluation.side not in {"LONG", "SHORT"}:
        return ScoredPullbackDecision(
            eligible=False,
            quality_score=0.0,
            hard_gates={"COMPLETE_EVENT": False},
            components={},
            reason_codes=("INCOMPLETE_EVENT_EVIDENCE",),
        )

    df = execution_df.reset_index(drop=True)
    p0 = int(evaluation.impulse_start_index)
    p1 = int(evaluation.impulse_end_index)
    p2 = int(evaluation.pullback_end_index)
    if p0 < 0 or p0 > p1 or p1 >= p2 or p2 + 1 >= len(df):
        return ScoredPullbackDecision(
            eligible=False,
            quality_score=0.0,
            hard_gates={"COMPLETE_EVENT": False},
            components={},
            reason_codes=("INVALID_EVENT_INDICES",),
        )

    impulse = df.iloc[p0 : p1 + 1]
    pullback = df.iloc[p1 + 1 : p2 + 1]
    trigger = df.iloc[p2 + 1 :]
    if min(len(impulse), len(pullback), len(trigger)) < 2:
        return ScoredPullbackDecision(
            eligible=False,
            quality_score=0.0,
            hard_gates={"COMPLETE_EVENT": False},
            components={},
            reason_codes=("INSUFFICIENT_PHASE_BARS",),
        )

    direction = 1 if evaluation.side == "LONG" else -1
    impulse_snapshot = calculate_directional_strength(impulse, lookback=len(impulse))
    pullback_snapshot = calculate_directional_strength(pullback, lookback=len(pullback))
    trigger_snapshot = calculate_directional_strength(trigger, lookback=len(trigger))

    if direction > 0:
        prior_trigger_extreme = float(trigger["high"].iloc[:-1].max())
        micro_reclaim = float(trigger["close"].iloc[-1]) > prior_trigger_extreme
    else:
        prior_trigger_extreme = float(trigger["low"].iloc[:-1].min())
        micro_reclaim = float(trigger["close"].iloc[-1]) < prior_trigger_extreme

    hard_gates = {
        "CONTEXT": bool(evaluation.gates.get("CONTEXT", False)),
        "EVENTS": bool(evaluation.gates.get("EVENTS", False)),
        "LEVEL": bool(evaluation.gates.get("LEVEL", False)),
        "IMPULSE_DIRECTION": impulse_snapshot.direction == direction,
        "PULLBACK_OPPOSES": pullback_snapshot.direction in {0, -direction},
        "TRIGGER_DIRECTION": trigger_snapshot.direction == direction,
        "MICRO_RECLAIM": bool(micro_reclaim),
    }
    hard_valid = all(hard_gates.values())

    impulse_score = _clip01(float(impulse_snapshot.composite_score))
    pullback_score = _clip01(float(pullback_snapshot.composite_score))
    trigger_score = _clip01(float(trigger_snapshot.composite_score))
    context_score = _clip01(float(evaluation.context_efficiency) / 0.60)
    level_score = _clip01(1.0 - float(evaluation.level_distance_atr) / max(cfg.level_tolerance_atr, 1e-9))
    weakness_score = _clip01(1.0 - pullback_score / max(impulse_score, 1e-9))

    # Five equally weighted ideas: higher-TF trend quality, structural location,
    # impulse quality, relative pullback weakness, and re-acceleration quality.
    # Pullback weakness uses a relative score instead of a fitted hard ratio.
    components = {
        "context": context_score,
        "location": level_score,
        "impulse": impulse_score,
        "pullback_weakness": weakness_score,
        "trigger": trigger_score,
    }
    quality_score = sum(components.values()) / len(components)
    eligible = bool(hard_valid and quality_score >= min_quality_score)

    reasons = ["STRUCTURAL_HARD_GATES_PASSED" if hard_valid else "STRUCTURAL_HARD_GATE_FAILED"]
    reasons.append("QUALITY_SCORE_PASSED" if quality_score >= min_quality_score else "QUALITY_SCORE_TOO_LOW")

    return ScoredPullbackDecision(
        eligible=eligible,
        quality_score=float(quality_score),
        hard_gates=hard_gates,
        components=components,
        reason_codes=tuple(reasons),
    )
