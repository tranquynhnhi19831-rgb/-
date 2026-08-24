from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategy.jianghe.breakout import evaluate_breakout_continuation_from_structure
from strategy.jianghe.pullback import evaluate_trend_pullback_from_structure
from strategy.jianghe.second_push import evaluate_second_push_failure_from_structure
from strategy.jianghe.types import MarketRegime, StructureSnapshot


@dataclass(frozen=True)
class PaperScenario:
    name: str
    symbol: str
    evaluation: object


def _bull_pullback_execution() -> pd.DataFrame:
    rows = []
    price = 104.30
    for _ in range(8):
        open_ = price
        close = open_ + 0.22
        rows.append((open_, close + 0.08, open_ - 0.05, close))
        price = close
    for move in (-0.50, 0.25, -0.55, 0.30, -0.65):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.12, min(open_, close) - 0.12, close))
        price = close
    for move in (0.30, 0.38, 0.42):
        open_ = price
        close = open_ + move
        rows.append((open_, close + 0.08, open_ - 0.06, close))
        price = close
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _bull_breakout_execution() -> pd.DataFrame:
    rows = [
        (108.50, 108.90, 108.20, 108.70),
        (108.70, 109.10, 108.40, 108.90),
        (108.90, 109.25, 108.65, 109.05),
        (109.05, 109.40, 108.80, 109.20),
        (109.20, 109.55, 109.00, 109.35),
        (109.35, 109.70, 109.15, 109.50),
        (109.50, 109.78, 109.35, 109.62),
        (109.62, 109.90, 109.48, 109.72),
        (109.72, 109.94, 109.58, 109.78),
        (109.78, 109.98, 109.64, 109.84),
        (109.84, 110.00, 109.72, 109.88),
        (109.88, 110.02, 109.78, 109.92),
        (109.92, 110.50, 109.85, 110.42),
        (110.42, 110.80, 110.35, 110.72),
        (110.70, 111.00, 110.62, 110.94),
        (110.94, 111.18, 110.85, 111.10),
        (111.10, 111.40, 111.02, 111.32),
    ]
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def _second_push_execution() -> pd.DataFrame:
    rows = []
    price = 107.30
    for move in (0.45, 0.42, 0.38, 0.35, 0.32, 0.28):
        open_ = price
        close = open_ + move
        rows.append((open_, close + 0.10, open_ - 0.06, close))
        price = close
    for move in (-0.38, -0.32, 0.10, -0.28):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.10, min(open_, close) - 0.10, close))
        price = close
    for move in (0.18, 0.16, 0.14, -0.10, 0.12, 0.08):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.10, min(open_, close) - 0.10, close))
        price = close
    for move in (-0.28, -0.34, -0.40):
        open_ = price
        close = open_ + move
        rows.append((open_, max(open_, close) + 0.08, min(open_, close) - 0.08, close))
        price = close
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def scenario_for_index(index: int, symbol: str) -> PaperScenario:
    kind = index % 3
    if kind == 0:
        structure = StructureSnapshot(
            regime=MarketRegime.BULL_TREND,
            trend_efficiency=0.46,
            net_direction=1,
            last_high_1=106.8,
            last_high_2=107.6,
            last_low_1=103.9,
            last_low_2=104.7,
            swing_high_count=4,
            swing_low_count=4,
        )
        evaluation = evaluate_trend_pullback_from_structure(structure, _bull_pullback_execution())
        return PaperScenario("TREND_PULLBACK_CONTINUATION", symbol, evaluation)

    if kind == 1:
        structure = StructureSnapshot(
            regime=MarketRegime.BULL_TREND,
            trend_efficiency=0.52,
            net_direction=1,
            last_high_1=109.20,
            last_high_2=110.00,
            last_low_1=106.80,
            last_low_2=107.60,
            swing_high_count=4,
            swing_low_count=4,
        )
        evaluation = evaluate_breakout_continuation_from_structure(structure, _bull_breakout_execution())
        return PaperScenario("BREAKOUT_CONTINUATION", symbol, evaluation)

    structure = StructureSnapshot(
        regime=MarketRegime.RANGE,
        trend_efficiency=0.18,
        net_direction=0,
        last_high_1=109.30,
        last_high_2=109.50,
        last_low_1=106.70,
        last_low_2=106.50,
        swing_high_count=5,
        swing_low_count=5,
    )
    evaluation = evaluate_second_push_failure_from_structure(structure, _second_push_execution())
    return PaperScenario("SECOND_PUSH_FAILURE", symbol, evaluation)
