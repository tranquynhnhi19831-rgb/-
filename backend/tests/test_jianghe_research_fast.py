import pandas as pd

import backtest.jianghe_research_fast as research_fast
import backtest.jianghe_runner as standard
from backtest.jianghe_research_fast import generate_jianghe_signals_research_fast
from backtest.jianghe_runner import JiangheRunnerConfig, SETUP_PULLBACK, generate_jianghe_signals_fast
from strategy.jianghe.types import MarketRegime, StructureSnapshot


class _FakePullback:
    candidate = True
    side = "LONG"
    invalidation_reference = 99.0
    setup = SETUP_PULLBACK
    entry_reference = 100.0

    def to_dict(self):
        return {"context_efficiency": 0.50}


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


def test_research_fast_path_matches_standard_candidate_and_cooldown_semantics(monkeypatch):
    context = _frame(["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"])
    execution = _frame(
        pd.date_range("2026-01-01T00:15:00Z", periods=6, freq="min")
    )
    structure = _bull_structure()

    monkeypatch.setattr(standard, "classify_structure", lambda df: structure)
    monkeypatch.setattr(research_fast, "classify_structure", lambda df: structure)
    monkeypatch.setattr(standard, "evaluate_trend_pullback_from_structure", lambda *args: _FakePullback())
    monkeypatch.setattr(research_fast, "evaluate_trend_pullback_from_structure", lambda *args: _FakePullback())

    cfg = JiangheRunnerConfig(
        context_lookback=10,
        execution_lookback=10,
        min_context_bars=1,
        min_execution_bars=1,
        signal_cooldown_bars=2,
        enabled_setups=(SETUP_PULLBACK,),
    )

    expected = generate_jianghe_signals_fast(context, execution, cfg)
    actual = generate_jianghe_signals_research_fast(context, execution, cfg)

    assert [signal.index for signal in actual] == [0, 3]
    assert actual == expected
