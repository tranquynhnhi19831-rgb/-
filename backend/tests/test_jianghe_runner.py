from types import SimpleNamespace

import pandas as pd

import backtest.jianghe_runner as runner
from backtest.jianghe_runner import JiangheRunnerConfig, SETUP_PULLBACK, generate_jianghe_signals


def _frame(timestamps):
    count = len(timestamps)
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps, utc=True),
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": [100.0] * count,
        }
    )


def test_runner_never_exposes_future_context_bar(monkeypatch):
    context = _frame(
        [
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T00:45:00Z",
        ]
    )
    execution = _frame(
        [
            "2026-01-01T00:05:00Z",
            "2026-01-01T00:10:00Z",
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:20:00Z",
            "2026-01-01T00:25:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T00:35:00Z",
        ]
    )
    seen_context_lengths = []

    def fake_classify(df):
        seen_context_lengths.append(len(df))
        return object()

    def fake_pullback(structure, df):
        return SimpleNamespace(candidate=False)

    monkeypatch.setattr(runner, "classify_structure", fake_classify)
    monkeypatch.setattr(runner, "evaluate_trend_pullback_from_structure", fake_pullback)

    cfg = JiangheRunnerConfig(
        context_lookback=10,
        execution_lookback=10,
        min_context_bars=1,
        min_execution_bars=2,
        signal_cooldown_bars=0,
        enabled_setups=(SETUP_PULLBACK,),
    )
    signals = generate_jianghe_signals(context, execution, cfg)

    assert signals == []
    # At 00:15 only the first 15m candle is available; the 00:30 candle
    # cannot be used by 00:20 or 00:25 execution decisions.
    assert seen_context_lengths == [1, 1, 1, 2, 2]
