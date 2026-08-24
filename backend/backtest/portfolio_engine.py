from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

import pandas as pd

from backtest.types import BacktestConfig
from config import INITIAL_TRADING_UNIVERSE


@dataclass(frozen=True)
class PortfolioSignal:
    symbol: str
    index: int
    setup: str
    side: str
    invalidation_reference: float
    score: float
    timestamp: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.symbol not in INITIAL_TRADING_UNIVERSE:
            raise ValueError(f"signal outside fixed universe: {self.symbol}")
        if self.index < 0:
            raise ValueError("signal index must be >= 0")
        if self.side not in {"LONG", "SHORT"}:
            raise ValueError("side must be LONG or SHORT")
        if self.invalidation_reference <= 0:
            raise ValueError("invalidation_reference must be > 0")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("score must be in [0, 1]")


@dataclass(frozen=True)
class PortfolioTrade:
    symbol: str
    setup: str
    side: str
    score: float
    signal_time: Any
    entry_time: Any
    exit_time: Any
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
class PortfolioBacktestResult:
    config: BacktestConfig
    trades: tuple[PortfolioTrade, ...]
    metrics: dict[str, Any]
    equity_curve: tuple[float, ...]


class SevenSymbolPortfolioBacktester:
    """Shared-100U, globally single-position portfolio replay.

    All symbols compete for the same capital. Signals known at the same close are
    ranked by quality score, then by the fixed universe order. One chosen trade
    blocks every other symbol until it exits. Daily trade/loss and consecutive-
    loss limits are global, matching the intended autonomous runtime semantics.

    The consecutive-loss guard is a UTC-day cooldown, not a permanent account
    lock. Three losses can block the remainder of that UTC day, but the next UTC
    day starts with a fresh loss streak.
    """

    def __init__(
        self,
        config: BacktestConfig | None = None,
        *,
        max_trades_per_day: int = 3,
        max_daily_loss: float = 0.02,
        max_consecutive_losses: int = 3,
    ) -> None:
        self.config = config or BacktestConfig(reward_risk=1.8)
        self.config.validate()
        if max_trades_per_day < 1:
            raise ValueError("max_trades_per_day must be >= 1")
        if not 0 < max_daily_loss <= 1:
            raise ValueError("max_daily_loss must be in (0, 1]")
        if max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be >= 1")
        self.max_trades_per_day = int(max_trades_per_day)
        self.max_daily_loss = float(max_daily_loss)
        self.max_consecutive_losses = int(max_consecutive_losses)

    @staticmethod
    def _prepare_bars(symbol: str, bars: pd.DataFrame) -> pd.DataFrame:
        required = {"timestamp", "open", "high", "low", "close"}
        missing = required.difference(bars.columns)
        if missing:
            raise ValueError(f"{symbol} missing columns: {sorted(missing)}")
        out = bars.copy().reset_index(drop=True)
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
        if not out["timestamp"].is_monotonic_increasing:
            raise ValueError(f"{symbol} bars must be chronological")
        return out

    @staticmethod
    def _apply_slippage(price: float, side: str, *, is_entry: bool, bps: float) -> float:
        rate = float(bps) / 10_000.0
        if side == "LONG":
            return float(price) * (1.0 + rate if is_entry else 1.0 - rate)
        return float(price) * (1.0 - rate if is_entry else 1.0 + rate)

    @staticmethod
    def _funding_cost(bars: pd.DataFrame, side: str, notional: float) -> float:
        if "funding_rate" not in bars.columns:
            return 0.0
        rates = bars["funding_rate"].fillna(0.0).astype(float)
        return float(notional * (1.0 if side == "LONG" else -1.0) * rates.sum())

    @staticmethod
    def _universe_rank(symbol: str) -> int:
        return INITIAL_TRADING_UNIVERSE.index(symbol)

    def _simulate_trade(
        self,
        bars: pd.DataFrame,
        signal: PortfolioSignal,
        equity: float,
    ) -> PortfolioTrade | None:
        cfg = self.config
        entry_index = signal.index + 1
        if entry_index >= len(bars):
            return None

        raw_entry = float(bars.loc[entry_index, "open"])
        entry = self._apply_slippage(raw_entry, signal.side, is_entry=True, bps=cfg.slippage_bps)
        stop = float(signal.invalidation_reference)
        stop_distance = entry - stop if signal.side == "LONG" else stop - entry
        if stop_distance <= 0:
            return None

        risk_amount = float(equity) * cfg.risk_per_trade
        risk_qty = risk_amount / stop_distance
        max_notional = float(equity) * cfg.max_margin_fraction * cfg.leverage
        margin_qty = max_notional / max(entry, 1e-12)
        quantity = min(risk_qty, margin_qty)
        if quantity <= 0:
            return None

        target = (
            entry + cfg.reward_risk * stop_distance
            if signal.side == "LONG"
            else entry - cfg.reward_risk * stop_distance
        )
        max_exit_index = min(len(bars) - 1, entry_index + cfg.max_hold_bars - 1)
        exit_index = max_exit_index
        exit_reason = "TIME"
        raw_exit = float(bars.loc[max_exit_index, "close"])

        for i in range(entry_index, max_exit_index + 1):
            open_i = float(bars.loc[i, "open"])
            high = float(bars.loc[i, "high"])
            low = float(bars.loc[i, "low"])
            if signal.side == "LONG" and open_i <= stop:
                raw_exit, exit_reason, exit_index = open_i, "STOP_GAP", i
                break
            if signal.side == "SHORT" and open_i >= stop:
                raw_exit, exit_reason, exit_index = open_i, "STOP_GAP", i
                break

            hit_stop = low <= stop if signal.side == "LONG" else high >= stop
            hit_target = high >= target if signal.side == "LONG" else low <= target
            if hit_stop and hit_target:
                raw_exit = stop if cfg.same_bar_policy == "STOP_FIRST" else target
                exit_reason = "STOP" if cfg.same_bar_policy == "STOP_FIRST" else "TARGET"
                exit_index = i
                break
            if hit_stop:
                raw_exit, exit_reason, exit_index = stop, "STOP", i
                break
            if hit_target:
                raw_exit, exit_reason, exit_index = target, "TARGET", i
                break

        exit_price = self._apply_slippage(raw_exit, signal.side, is_entry=False, bps=cfg.slippage_bps)
        sign = 1.0 if signal.side == "LONG" else -1.0
        gross = sign * (exit_price - entry) * quantity
        entry_notional = entry * quantity
        exit_notional = exit_price * quantity
        fees = (abs(entry_notional) + abs(exit_notional)) * cfg.fee_rate
        funding = self._funding_cost(bars.iloc[entry_index : exit_index + 1], signal.side, abs(entry_notional))
        net = gross - fees - funding
        risk_denom = stop_distance * quantity
        signal_time = pd.to_datetime(signal.timestamp, utc=True) if signal.timestamp is not None else bars.loc[signal.index, "timestamp"]
        return PortfolioTrade(
            symbol=signal.symbol,
            setup=signal.setup,
            side=signal.side,
            score=float(signal.score),
            signal_time=signal_time,
            entry_time=bars.loc[entry_index, "timestamp"],
            exit_time=bars.loc[exit_index, "timestamp"],
            entry_price=float(entry),
            exit_price=float(exit_price),
            stop_price=stop,
            target_price=float(target),
            quantity=float(quantity),
            gross_pnl=float(gross),
            fees=float(fees),
            funding=float(funding),
            net_pnl=float(net),
            r_multiple=float(net / risk_denom if risk_denom > 0 else 0.0),
            exit_reason=exit_reason,
            equity_before=float(equity),
            equity_after=max(0.0, float(equity) + float(net)),
        )

    def run(
        self,
        bars_by_symbol: dict[str, pd.DataFrame],
        signals: Iterable[PortfolioSignal],
    ) -> PortfolioBacktestResult:
        frames = {symbol: self._prepare_bars(symbol, bars) for symbol, bars in bars_by_symbol.items()}
        missing_universe = [symbol for symbol in frames if symbol not in INITIAL_TRADING_UNIVERSE]
        if missing_universe:
            raise ValueError(f"bars outside fixed universe: {sorted(missing_universe)}")

        grouped: dict[pd.Timestamp, list[PortfolioSignal]] = defaultdict(list)
        for signal in signals:
            signal.validate()
            if signal.symbol not in frames:
                raise ValueError(f"missing bars for signal symbol: {signal.symbol}")
            frame = frames[signal.symbol]
            if signal.index >= len(frame):
                raise ValueError(f"signal index outside bars: {signal.symbol} index={signal.index}")
            ts = pd.to_datetime(signal.timestamp, utc=True) if signal.timestamp is not None else frame.loc[signal.index, "timestamp"]
            grouped[ts].append(signal)

        equity = float(self.config.initial_equity)
        equity_curve = [equity]
        trades: list[PortfolioTrade] = []
        next_free_time: pd.Timestamp | None = None
        trades_per_day: dict[Any, int] = defaultdict(int)
        realized_per_day: dict[Any, float] = defaultdict(float)
        day_start_equity: dict[Any, float] = {}
        consecutive_losses = 0
        loss_streak_day = None
        arbitration_skips = 0
        occupied_skips = 0
        risk_skips = 0
        invalid_skips = 0

        for signal_time in sorted(grouped):
            same_time = grouped[signal_time]
            if next_free_time is not None and signal_time < next_free_time:
                occupied_skips += len(same_time)
                continue

            ranked = sorted(
                same_time,
                key=lambda item: (-float(item.score), self._universe_rank(item.symbol), item.setup, item.side),
            )
            day = signal_time.date()
            if loss_streak_day != day:
                consecutive_losses = 0
                loss_streak_day = day
            if day not in day_start_equity:
                day_start_equity[day] = equity
            if trades_per_day[day] >= self.max_trades_per_day:
                risk_skips += len(ranked)
                continue
            if realized_per_day[day] <= -(day_start_equity[day] * self.max_daily_loss):
                risk_skips += len(ranked)
                continue
            if consecutive_losses >= self.max_consecutive_losses:
                risk_skips += len(ranked)
                continue

            chosen: PortfolioTrade | None = None
            chosen_signal: PortfolioSignal | None = None
            for candidate in ranked:
                maybe = self._simulate_trade(frames[candidate.symbol], candidate, equity)
                if maybe is not None:
                    chosen, chosen_signal = maybe, candidate
                    break
                invalid_skips += 1

            if chosen is None or chosen_signal is None:
                continue
            arbitration_skips += max(0, len(ranked) - 1)
            equity = float(chosen.equity_after)
            equity_curve.append(equity)
            trades.append(chosen)
            entry_day = pd.to_datetime(chosen.entry_time, utc=True).date()
            exit_day = pd.to_datetime(chosen.exit_time, utc=True).date()
            if entry_day not in day_start_equity:
                day_start_equity[entry_day] = float(chosen.equity_before)
            trades_per_day[entry_day] += 1
            realized_per_day[exit_day] += float(chosen.net_pnl)

            # A loss streak belongs to the UTC day on which the result is
            # realized. A trade spanning midnight must not carry yesterday's
            # streak into today's cooldown, and a new UTC day always starts at 0.
            if loss_streak_day != exit_day:
                consecutive_losses = 0
                loss_streak_day = exit_day
            consecutive_losses = consecutive_losses + 1 if chosen.net_pnl < 0 else 0

            next_free_time = pd.to_datetime(chosen.exit_time, utc=True)
            if equity <= 0:
                break

        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl < 0]
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        peak = float(self.config.initial_equity)
        max_drawdown = 0.0
        for point in equity_curve:
            peak = max(peak, float(point))
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - float(point)) / peak)

        by_symbol: dict[str, dict[str, Any]] = {}
        for symbol in INITIAL_TRADING_UNIVERSE:
            subset = [t for t in trades if t.symbol == symbol]
            if not subset:
                continue
            by_symbol[symbol] = {
                "trades": len(subset),
                "wins": sum(1 for t in subset if t.net_pnl > 0),
                "net_pnl": sum(t.net_pnl for t in subset),
                "fees": sum(t.fees for t in subset),
            }

        metrics = {
            "initial_equity": float(self.config.initial_equity),
            "final_equity": float(equity),
            "net_pnl": float(equity - self.config.initial_equity),
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(trades)) if trades else 0.0,
            "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
            "expectancy": (sum(t.net_pnl for t in trades) / len(trades)) if trades else 0.0,
            "max_drawdown": float(max_drawdown),
            "fees": float(sum(t.fees for t in trades)),
            "funding": float(sum(t.funding for t in trades)),
            "arbitration_skips": arbitration_skips,
            "occupied_skips": occupied_skips,
            "risk_skips": risk_skips,
            "invalid_skips": invalid_skips,
            "by_symbol": by_symbol,
            "max_trades_per_day": self.max_trades_per_day,
            "max_daily_loss": self.max_daily_loss,
            "max_consecutive_losses": self.max_consecutive_losses,
            "consecutive_loss_scope": "UTC_DAY",
            "max_open_positions": 1,
        }
        return PortfolioBacktestResult(
            config=self.config,
            trades=tuple(trades),
            metrics=metrics,
            equity_curve=tuple(equity_curve),
        )
