"""Quantitative translation of Jianghe-style price-action concepts.

The package keeps raw features separate from trading decisions so every
experimental threshold can be backtested and audited.
"""

from strategy.jianghe.breakout import (
    BreakoutConfig,
    BreakoutEvaluation,
    evaluate_breakout_continuation,
    evaluate_breakout_continuation_from_structure,
)
from strategy.jianghe.pullback import (
    PullbackConfig,
    PullbackEvaluation,
    evaluate_trend_pullback,
    evaluate_trend_pullback_from_structure,
)
from strategy.jianghe.structure import classify_structure, find_confirmed_swings
from strategy.jianghe.strength import calculate_directional_strength, compare_strength
from strategy.jianghe.types import MarketRegime, StrengthSnapshot, StructureSnapshot

__all__ = [
    "BreakoutConfig",
    "BreakoutEvaluation",
    "MarketRegime",
    "PullbackConfig",
    "PullbackEvaluation",
    "StrengthSnapshot",
    "StructureSnapshot",
    "calculate_directional_strength",
    "classify_structure",
    "compare_strength",
    "evaluate_breakout_continuation",
    "evaluate_breakout_continuation_from_structure",
    "evaluate_trend_pullback",
    "evaluate_trend_pullback_from_structure",
    "find_confirmed_swings",
]
