import pandas as pd

import backtest.jianghe_event_runner as runner
from backtest.jianghe_event_runner import EventPullbackRunnerConfig, generate_event_pullback_signals_fast
from strategy.jianghe.types import MarketRegime, StructureSnapshot


class _FakeEvaluation:
    candidate = True
    side = "LONG"
    invalidation_reference = 99.0
    pullback_end_index = 1
    setup = "TREND_PULLBACK_EVENT_V3"
    entry_reference = 100.0

    def to_dict(self):
        return {"pullback_end_index": self.pullback_end_index}


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


def _bull_structure():
    return StructureSnapshot(
        regime=MarketRegime.BULL_TREND,
        trend_efficiency=0.50,
        net_direction=1,
        last_high_1=100.0,
        last_high_2=101.0,
        last_low_1=98.0,
        last_low_2=99.0,
        swing_high_count=4,
        swing_low_count=4,
    )


def test_same_confirmed_pullback_event_emits_only_once(monkeypatch):
    context = _frame(["2026-01-01T00:00:00Z"])
    execution = _frame(
        [
            "2026-01-01T00:01:00Z",
            "2026-01-01T00:02:00Z",
            "2026-01-01T00:03:00Z",
            "2026-01-01T00:04:00Z",
            "2026-01-01T00:05:00Z",
        ]
    )

    monkeypatch.setattr(runner, "classify_structure", lambda df: _bull_structure())

    def fake_evaluate(structure, ex, config):
        if len(ex) < 3:
            return type("NoCandidate", (), {"candidate": False})()
        return _FakeEvaluation()

    monkeypatch.setattr(runner, "evaluate_event_pullback_from_structure", fake_evaluate)

    cfg = EventPullbackRunnerConfig(
        context_lookback=10,
        execution_lookback=10,
        min_context_bars=1,
        min_execution_bars=1,
        signal_cooldown_bars=0,
    )
    signals = generate_event_pullback_signals_fast(context, execution, cfg)

    assert len(signals) == 1
    assert signals[0].index == 2
    assert signals[0].metadata["event_pullback_index_abs"] == 1
