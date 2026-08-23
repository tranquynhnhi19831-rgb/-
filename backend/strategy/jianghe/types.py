from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MarketRegime(str, Enum):
    BULL_TREND = "BULL_TREND"
    BEAR_TREND = "BEAR_TREND"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    confirmed_at: int
    price: float
    kind: str  # "HIGH" or "LOW"


@dataclass(frozen=True)
class StructureSnapshot:
    regime: MarketRegime
    trend_efficiency: float
    net_direction: int
    last_high_1: float | None
    last_high_2: float | None
    last_low_1: float | None
    last_low_2: float | None
    swing_high_count: int
    swing_low_count: int
    evidence_grade: str = "D_EXPERIMENTAL_QUANT_TRANSLATION"


@dataclass(frozen=True)
class StrengthSnapshot:
    direction: int
    composite_score: float
    displacement_atr: float
    speed_atr_per_bar: float
    body_efficiency: float
    directional_consistency: float
    close_location: float
    overlap_ratio: float
    trend_efficiency: float
    atr: float
    bars: int
    evidence_grade: str = "D_EXPERIMENTAL_QUANT_TRANSLATION"


@dataclass(frozen=True)
class StrengthTransition:
    state: str  # STRENGTHENING / WEAKENING / FLAT / DIRECTION_CHANGE
    score_delta: float
    direction_changed: bool
    previous_score: float
    current_score: float
