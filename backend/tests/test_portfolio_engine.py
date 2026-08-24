from __future__ import annotations

import pandas as pd

from backtest.portfolio_engine import PortfolioSignal, SevenSymbolPortfolioBacktester
from backtest.types import BacktestConfig


def _bars(start="2026-01-01", rows=20, base=100.0):
    ts = pd.date_range(start=start, periods=rows, freq="1min", tz="UTC")
    data = []
    price = base
    for i, timestamp in enumerate(ts):
        open_ = price
        close = open_ + 0.1
        data.append(
            {
                "timestamp": timestamp,
                "open": open_,
                "high": max(open_, close) + 0.3,
                "low": min(open_, close) - 0.3,
                "close": close,
                "volume": 1.0,
            }
        )
        price = close
    return pd.DataFrame(data)


def test_simultaneous_candidates_share_one_account_and_highest_score_wins():
    eth = _bars(base=100)
    sol = _bars(base=50)
    # Make SOL hit target on its entry bar while ETH would also be valid.
    sol.loc[2, "high"] = 55.0
    signals = [
        PortfolioSignal(
            symbol="ETH/USDT",
            index=1,
            setup="A",
            side="LONG",
            invalidation_reference=98.0,
            score=0.70,
        ),
        PortfolioSignal(
            symbol="SOL/USDT",
            index=1,
            setup="B",
            side="LONG",
            invalidation_reference=49.0,
            score=0.90,
        ),
    ]
    result = SevenSymbolPortfolioBacktester(
        BacktestConfig(initial_equity=100, reward_risk=1.8, max_hold_bars=4)
    ).run({"ETH/USDT": eth, "SOL/USDT": sol}, signals)

    assert len(result.trades) == 1
    assert result.trades[0].symbol == "SOL/USDT"
    assert result.metrics["arbitration_skips"] == 1


def test_global_daily_trade_cap_applies_across_symbols():
    btc = _bars(rows=40, base=100)
    eth = _bars(rows=40, base=100)
    # Stops far enough away that each trade times out quickly with max_hold=1.
    signals = [
        PortfolioSignal("BTC/USDT", 1, "A", "LONG", 95.0, 0.9),
        PortfolioSignal("ETH/USDT", 5, "A", "LONG", 95.0, 0.9),
        PortfolioSignal("BTC/USDT", 9, "A", "LONG", 95.0, 0.9),
        PortfolioSignal("ETH/USDT", 13, "A", "LONG", 95.0, 0.9),
    ]
    result = SevenSymbolPortfolioBacktester(
        BacktestConfig(initial_equity=100, reward_risk=1.8, max_hold_bars=1),
        max_trades_per_day=3,
    ).run({"BTC/USDT": btc, "ETH/USDT": eth}, signals)

    assert len(result.trades) == 3
    assert result.metrics["risk_skips"] >= 1


def test_portfolio_never_uses_more_than_shared_equity_curve():
    btc = _bars(rows=20, base=100)
    btc.loc[2, "low"] = 90.0
    signal = PortfolioSignal("BTC/USDT", 1, "A", "LONG", 98.0, 0.9)
    result = SevenSymbolPortfolioBacktester(
        BacktestConfig(initial_equity=100, reward_risk=1.8, max_hold_bars=4)
    ).run({"BTC/USDT": btc}, [signal])
    assert result.equity_curve[0] == 100.0
    assert len(result.equity_curve) == len(result.trades) + 1
    assert result.metrics["max_open_positions"] == 1


def test_three_losses_stop_only_the_current_utc_day_then_reset():
    btc = _bars(rows=1450, base=100)
    # Three deterministic stop-outs on Jan 1, then another valid stop-out on
    # Jan 2. If the loss streak were global/permanent, the Jan 2 trade would
    # never be admitted.
    btc.loc[2, "low"] = 90.0
    btc.loc[6, "low"] = 90.0
    btc.loc[10, "low"] = 90.0
    btc.loc[1442, "low"] = 230.0

    signals = [
        PortfolioSignal("BTC/USDT", 1, "A", "LONG", 99.0, 0.9),
        PortfolioSignal("BTC/USDT", 5, "A", "LONG", 99.0, 0.9),
        PortfolioSignal("BTC/USDT", 9, "A", "LONG", 99.0, 0.9),
        PortfolioSignal("BTC/USDT", 1441, "A", "LONG", 243.0, 0.9),
    ]
    result = SevenSymbolPortfolioBacktester(
        BacktestConfig(initial_equity=100, reward_risk=1.8, max_hold_bars=4),
        max_trades_per_day=5,
        max_daily_loss=0.10,
        max_consecutive_losses=3,
    ).run({"BTC/USDT": btc}, signals)

    assert len(result.trades) == 4
    assert pd.to_datetime(result.trades[-1].signal_time, utc=True).date() == pd.Timestamp("2026-01-02").date()
    assert result.metrics["consecutive_loss_scope"] == "UTC_DAY"
