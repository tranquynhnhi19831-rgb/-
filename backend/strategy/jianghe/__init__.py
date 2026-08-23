"""Quantitative translation of Jianghe-style price-action concepts.

The package keeps raw features separate from trading decisions so every
experimental threshold can be backtested and audited.
"""

from strategy.jianghe.structure import classify_structure, find_confirmed_swings
from strategy.jianghe.strength import calculate_directional_strength, compare_strength
from strategy.jianghe.types import MarketRegime, StrengthSnapshot, StructureSnapshot

__all__ = [
    "MarketRegime",
    "StrengthSnapshot",
    "StructureSnapshot",
    "calculate_directional_strength",
    "classify_structure",
    "compare_strength",
    "find_confirmed_swings",
]
