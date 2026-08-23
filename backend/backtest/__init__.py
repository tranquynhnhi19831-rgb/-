"""Deterministic backtesting primitives for Jianghe strategy research."""

from backtest.engine import BacktestEngine
from backtest.types import BacktestConfig, BacktestResult, BacktestTrade, CandidateSignal

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "BacktestTrade",
    "CandidateSignal",
]
