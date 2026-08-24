from types import SimpleNamespace

import pandas as pd

import backtest.jianghe_multitimeframe_runner as mtf
from backtest.jianghe_multitimeframe_runner import (
    MultiTimeframeRunnerConfig,
    generate_multitimeframe_event_pullback_signals_fast,
    multitimeframe_alignment_allowed,
)
from strategy.jianghe.types import MarketRegime, StructureSnapshot


def _structure(regime: MarketRegime, efficiency: float = 0.40, net_direction: int | None = None):
    direction = 1 if regime == MarketRegime.BULL_TREND else -1 if regime == MarketRegime.BEAR_TREND else 0
    return StructureSnapshot(
        regime=regime,
        trend_efficiency=efficiency,
        net_direction=direction if net_direction is None else net_direction,
        last_high_1=100.0,
        last_high_2=101.0 if direction >= 0 else 99.0,
        last_low_1=98.0,
        last_low_2=99.0 if direction >= 0 else 97.0,
        swing_high_count=4,
        swing_low_count=4,
    )


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


def test_multitimeframe_alignment_accepts_confirmed_same_direction_trends():
    macro = _structure(MarketRegime.BULL_TREND, efficiency=0.35)
    context = _structure(MarketRegime.BULL_TREND, efficiency=0.42)

    assert multitimeframe_alignment_allowed(macro, context) is True


def test_multitimeframe_alignment_rejects_1h_15m_direction_conflict():
    macro = _structure(MarketRegime.BULL_TREND)
    context = _structure(MarketRegime.BEAR_TREND)

    assert multitimeframe_alignment_allowed(macro, context) is False


def test_multitimeframe_alignment_rejects_recent_path_against_structure():
    macro = _structure(MarketRegime.BULL_TREND, net_direction=-1)
    context = _structure(MarketRegime.BULL_TREND)

    assert multitimeframe_alignment_allowed(macro, context) is False


def test_multitimeframe_alignment_rejects_weak_macro_context():
    cfg = MultiTimeframeRunnerConfig(min_macro_efficiency=0.20)
    macro = _structure(MarketRegime.BULL_TREND, efficiency=0.19)
    context = _structure(MarketRegime.BULL_TREND, efficiency=0.40)

    assert multitimeframe_alignment_allowed(macro, context, cfg) is False


def test_runner_does_not_use_unclosed_1h_bar(monkeypatch):
    macro = _frame(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"])
    context = _frame(
        [
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T00:45:00Z",
            "2026-01-01T01:00:00Z",
        ]
    )
    execution = _frame(
        [
            "2026-01-01T00:30:00Z",
            "2026-01-01T00:45:00Z",
            "2026-01-01T00:59:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T01:01:00Z",
        ]
    )
    bull = _structure(MarketRegime.BULL_TREND)
    evaluations = []

    monkeypatch.setattr(mtf, "classify_structure", lambda df: bull)

    def fake_evaluate(structure, ex, config):
        evaluations.append(len(ex))
        return SimpleNamespace(candidate=False)

    monkeypatch.setattr(mtf, "evaluate_event_pullback_from_structure", fake_evaluate)

    cfg = MultiTimeframeRunnerConfig(
        macro_lookback=10,
        context_lookback=10,
        execution_lookback=10,
        min_macro_bars=1,
        min_context_bars=1,
        min_execution_bars=1,
        min_macro_efficiency=0.0,
        min_context_efficiency=0.0,
    )
    signals = generate_multitimeframe_event_pullback_signals_fast(macro, context, execution, cfg)

    assert signals == []
    # 00:30, 00:45 and 00:59 cannot see the 1h candle whose close is 01:00.
    # Evaluation starts only at 01:00 and continues at 01:01.
    assert evaluations == [4, 5]
