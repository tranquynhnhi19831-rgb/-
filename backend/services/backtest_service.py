from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from backtest.binance_data import attach_funding_rates, fetch_usdm_funding_rates, fetch_usdm_ohlcv
from backtest.engine import BacktestEngine
from backtest.jianghe_runner import ALL_SETUPS, JiangheRunnerConfig, generate_jianghe_signals
from backtest.types import BacktestConfig

MAX_API_RANGE_DAYS = 31


def _timestamp(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _timeframe_delta(timeframe: str) -> pd.Timedelta:
    unit = timeframe[-1]
    amount = int(timeframe[:-1])
    mapping = {"m": "minutes", "h": "hours", "d": "days"}
    if unit not in mapping or amount < 1:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return pd.Timedelta(**{mapping[unit]: amount})


def run_backtest(
    symbol: str,
    start: str,
    end: str,
    *,
    context_timeframe: str = "15m",
    execution_timeframe: str = "1m",
    enabled_setups: tuple[str, ...] = ALL_SETUPS,
    initial_equity: float = 100.0,
    risk_per_trade: float = 0.005,
    fee_rate: float = 0.0004,
    slippage_bps: float = 2.0,
    reward_risk: float = 1.5,
    leverage: float = 3.0,
    max_margin_fraction: float = 0.10,
) -> dict:
    """Run a real deterministic Binance-history backtest.

    This replaces the original random-number placeholder. Public market/funding
    history is fetched from Binance USDT-M without private API credentials.
    """
    start_ts = _timestamp(start)
    end_ts = _timestamp(end)
    if end_ts <= start_ts:
        raise ValueError("end must be after start")
    if end_ts - start_ts > pd.Timedelta(days=MAX_API_RANGE_DAYS):
        raise ValueError(
            f"API backtests are capped at {MAX_API_RANGE_DAYS} days per request; split longer studies into walk-forward windows"
        )

    runner_cfg = JiangheRunnerConfig(enabled_setups=tuple(enabled_setups))
    runner_cfg.validate()
    warmup = max(
        runner_cfg.context_lookback * _timeframe_delta(context_timeframe),
        runner_cfg.execution_lookback * _timeframe_delta(execution_timeframe),
    )
    warmup_start = start_ts - warmup

    context = fetch_usdm_ohlcv(
        symbol,
        context_timeframe,
        warmup_start.isoformat(),
        end_ts.isoformat(),
        max_bars=25_000,
    )
    execution = fetch_usdm_ohlcv(
        symbol,
        execution_timeframe,
        warmup_start.isoformat(),
        end_ts.isoformat(),
        max_bars=100_000,
    )
    if context.empty or execution.empty:
        raise ValueError("Binance returned no historical candles for the requested range")

    funding = fetch_usdm_funding_rates(symbol, start_ts.isoformat(), end_ts.isoformat())
    execution = attach_funding_rates(execution, funding)

    signals = generate_jianghe_signals(context, execution, runner_cfg)
    signals = [
        signal
        for signal in signals
        if signal.timestamp is not None and start_ts <= pd.Timestamp(signal.timestamp) < end_ts
    ]

    bt_cfg = BacktestConfig(
        initial_equity=initial_equity,
        risk_per_trade=risk_per_trade,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        reward_risk=reward_risk,
        leverage=leverage,
        max_margin_fraction=max_margin_fraction,
    )
    result = BacktestEngine(bt_cfg).run(execution, signals)

    trade_rows = [asdict(trade) for trade in result.trades]
    return {
        "symbol": symbol,
        "market": "BINANCE_USDT_M",
        "start": start_ts.isoformat(),
        "end": end_ts.isoformat(),
        "context_timeframe": context_timeframe,
        "execution_timeframe": execution_timeframe,
        "enabled_setups": list(enabled_setups),
        "execution_assumptions": asdict(bt_cfg),
        "bars": {
            "context": len(context),
            "execution": len(execution),
            "funding_events": len(funding),
        },
        "signals_generated": len(signals),
        "skipped_signals": result.skipped_signals,
        "metrics": result.metrics,
        "equity_curve": list(result.equity_curve),
        "trades": trade_rows[-500:],
        "trades_truncated": len(trade_rows) > 500,
        "research_warning": (
            "All Jianghe thresholds and execution assumptions remain experimental. "
            "A profitable in-sample result is not evidence of a durable edge."
        ),
    }
