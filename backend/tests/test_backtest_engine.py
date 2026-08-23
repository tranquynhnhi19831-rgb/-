import math

import pandas as pd

from backtest.engine import BacktestEngine
from backtest.types import BacktestConfig, CandidateSignal


def _bars(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_signal_enters_on_next_bar_and_hits_target():
    bars = _bars(
        [
            (99.5, 100.2, 99.2, 100.0),
            (100.0, 101.0, 99.5, 100.8),
            (100.8, 102.0, 100.5, 101.8),
        ]
    )
    cfg = BacktestConfig(
        fee_rate=0.0,
        slippage_bps=0.0,
        risk_per_trade=0.01,
        reward_risk=1.5,
        leverage=10,
        max_margin_fraction=1.0,
    )
    signal = CandidateSignal(index=0, setup="TEST", side="LONG", invalidation_reference=99.0)
    result = BacktestEngine(cfg).run(bars, [signal])

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_index == 1
    assert trade.entry_price == 100.0
    assert trade.exit_index == 2
    assert trade.exit_reason == "TARGET"
    assert trade.target_price == 101.5
    assert trade.quantity == 1.0
    assert trade.net_pnl == 1.5
    assert result.metrics["final_equity"] == 101.5


def test_same_bar_stop_and_target_defaults_to_conservative_stop_first():
    bars = _bars(
        [
            (100.0, 100.2, 99.8, 100.0),
            (100.0, 102.0, 98.5, 100.5),
        ]
    )
    cfg = BacktestConfig(
        fee_rate=0.0,
        slippage_bps=0.0,
        risk_per_trade=0.01,
        reward_risk=1.0,
        leverage=10,
        max_margin_fraction=1.0,
        same_bar_policy="STOP_FIRST",
    )
    signal = CandidateSignal(index=0, setup="TEST", side="LONG", invalidation_reference=99.0)
    trade = BacktestEngine(cfg).run(bars, [signal]).trades[0]

    assert trade.exit_reason == "STOP"
    assert trade.exit_price == 99.0
    assert trade.net_pnl == -1.0


def test_default_100u_profile_caps_notional_by_margin_fraction_and_leverage():
    bars = _bars(
        [
            (100.0, 100.1, 99.9, 100.0),
            (100.0, 101.0, 99.0, 100.5),
            (100.5, 101.0, 100.2, 100.6),
        ]
    )
    cfg = BacktestConfig(fee_rate=0.0, slippage_bps=0.0, max_hold_bars=2)
    # Risk sizing would allow 0.5 / 5 = 0.1 units, but margin cap is 100 * 10% * 3x = 30U => 0.3 units.
    # Here risk sizing is tighter, so change the stop to make risk sizing much larger than margin cap.
    signal = CandidateSignal(index=0, setup="TEST", side="LONG", invalidation_reference=99.9)
    trade = BacktestEngine(cfg).run(bars, [signal]).trades[0]

    assert math.isclose(trade.entry_price * trade.quantity, 30.0, rel_tol=1e-9)


def test_fees_slippage_and_positive_long_funding_reduce_net_pnl():
    bars = pd.DataFrame(
        [
            (100.0, 100.2, 99.8, 100.0, 0.0),
            (100.0, 101.0, 99.5, 100.8, 0.0001),
            (100.8, 102.0, 100.5, 101.8, 0.0001),
        ],
        columns=["open", "high", "low", "close", "funding_rate"],
    )
    cfg = BacktestConfig(
        fee_rate=0.0004,
        slippage_bps=2.0,
        risk_per_trade=0.01,
        reward_risk=1.5,
        leverage=10,
        max_margin_fraction=1.0,
    )
    signal = CandidateSignal(index=0, setup="TEST", side="LONG", invalidation_reference=99.0)
    trade = BacktestEngine(cfg).run(bars, [signal]).trades[0]

    assert trade.fees > 0
    assert trade.funding > 0
    assert trade.net_pnl < trade.gross_pnl


def test_overlapping_signals_are_skipped_while_position_is_open():
    bars = _bars(
        [
            (100.0, 100.1, 99.9, 100.0),
            (100.0, 100.5, 99.5, 100.2),
            (100.2, 100.6, 99.7, 100.1),
            (100.1, 100.4, 99.8, 100.2),
            (100.2, 100.3, 99.9, 100.1),
        ]
    )
    cfg = BacktestConfig(
        fee_rate=0.0,
        slippage_bps=0.0,
        reward_risk=10.0,
        max_hold_bars=3,
        leverage=10,
        max_margin_fraction=1.0,
    )
    signals = [
        CandidateSignal(index=0, setup="A", side="LONG", invalidation_reference=98.0),
        CandidateSignal(index=1, setup="B", side="LONG", invalidation_reference=98.0),
    ]
    result = BacktestEngine(cfg).run(bars, signals)

    assert len(result.trades) == 1
    assert result.skipped_signals == 1
