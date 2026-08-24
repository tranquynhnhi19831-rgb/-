from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BacktestConfig:
    """Execution assumptions for deterministic research backtests.

    These are research/execution parameters, not Jianghe's claimed rules.
    ``max_friction_to_planned_risk`` is opt-in so existing baselines remain
    byte-for-byte comparable unless an experiment explicitly enables it.
    """

    initial_equity: float = 100.0
    risk_per_trade: float = 0.005
    fee_rate: float = 0.0004
    slippage_bps: float = 2.0
    reward_risk: float = 1.5
    max_hold_bars: int = 64
    leverage: float = 3.0
    max_margin_fraction: float = 0.10
    same_bar_policy: str = "STOP_FIRST"
    max_friction_to_planned_risk: float | None = None

    def validate(self) -> None:
        if self.initial_equity <= 0:
            raise ValueError("initial_equity must be > 0")
        if not 0 < self.risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be in (0, 1]")
        if self.fee_rate < 0 or self.slippage_bps < 0:
            raise ValueError("fee/slippage must be >= 0")
        if self.reward_risk <= 0:
            raise ValueError("reward_risk must be > 0")
        if self.max_hold_bars < 1:
            raise ValueError("max_hold_bars must be >= 1")
        if self.leverage <= 0:
            raise ValueError("leverage must be > 0")
        if not 0 < self.max_margin_fraction <= 1:
            raise ValueError("max_margin_fraction must be in (0, 1]")
        if self.same_bar_policy not in {"STOP_FIRST", "TARGET_FIRST"}:
            raise ValueError("same_bar_policy must be STOP_FIRST or TARGET_FIRST")
        if self.max_friction_to_planned_risk is not None and not (
            0 < self.max_friction_to_planned_risk < 1
        ):
            raise ValueError("max_friction_to_planned_risk must be in (0, 1) or None")


@dataclass(frozen=True)
class CandidateSignal:
    index: int
    setup: str
    side: str
    invalidation_reference: float
    entry_reference: float | None = None
    timestamp: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.index < 0:
            raise ValueError("signal index must be >= 0")
        if self.side not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")
        if self.invalidation_reference <= 0:
            raise ValueError("invalidation_reference must be > 0")


@dataclass(frozen=True)
class BacktestTrade:
    setup: str
    side: str
    signal_index: int
    entry_index: int
    exit_index: int
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    quantity: float
    gross_pnl: float
    fees: float
    funding: float
    net_pnl: float
    r_multiple: float
    exit_reason: str
    equity_before: float
    equity_after: float


@dataclass(frozen=True)
class BacktestResult:
    config: BacktestConfig
    trades: tuple[BacktestTrade, ...]
    metrics: dict[str, Any]
    equity_curve: tuple[float, ...]
    skipped_signals: int
