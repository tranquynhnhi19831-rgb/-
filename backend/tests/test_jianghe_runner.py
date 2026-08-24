from types import SimpleNamespace

import pandas as pd

import backtest.jianghe_runner as runner
from backtest.jianghe_runner import (
    JiangheRunnerConfig,
    SETUP_PULLBACK,
    generate_jianghe_signals,
    generate_jianghe_signals_fast,
    quality_first_v2_config,
)
from strategy.jianghe.types import MarketRegime, StructureSnapshot


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


def _range_structure():
    return StructureSnapshot(
        regime=MarketRegime.RANGE,
        trend_efficiency=0.0,
        net_direction=0,
        last_high_1=101.0,
        last_high_2=101.0,
        last_low_1=99.0,
        last_low_2=99.0,
        swing_high_count=2,
        swing_low_count=2,
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
        return _range_structure()

    def fake_pullback(structure, df, config):
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


def test_quality_v2_is_explicitly_stricter_than_baseline():
    baseline = JiangheRunnerConfig()
    v2 = quality_first_v2_config()

    assert baseline.min_context_efficiency == 0.0
    assert baseline.require_context_direction_alignment is False
    assert baseline.allow_second_push_range is True

    assert v2.min_context_efficiency > 0.0
    assert v2.require_context_direction_alignment is True
    assert v2.allow_second_push_range is False
    assert v2.require_second_push_trend_alignment is True
    assert v2.pullback_config.min_impulse_strength > baseline.pullback_config.min_impulse_strength
    assert v2.breakout_config.min_tests > baseline.breakout_config.min_tests
    assert v2.second_push_config.max_acceptance_fraction < baseline.second_push_config.max_acceptance_fraction


def test_quality_v2_rejects_recent_direction_against_confirmed_trend(monkeypatch):
    timestamps = pd.date_range("2026-01-01T00:01:00Z", periods=40, freq="min")
    execution = _frame(timestamps)
    context = _frame(pd.date_range("2025-12-31T18:15:00Z", periods=40, freq="15min"))

    misaligned = StructureSnapshot(
        regime=MarketRegime.BULL_TREND,
        trend_efficiency=0.50,
        net_direction=-1,
        last_high_1=100.0,
        last_high_2=101.0,
        last_low_1=98.0,
        last_low_2=99.0,
        swing_high_count=3,
        swing_low_count=3,
    )

    monkeypatch.setattr(runner, "classify_structure", lambda df: misaligned)

    def must_not_evaluate(*args, **kwargs):
        raise AssertionError("misaligned context should be rejected before setup evaluation")

    monkeypatch.setattr(runner, "evaluate_trend_pullback_from_structure", must_not_evaluate)
    monkeypatch.setattr(runner, "evaluate_breakout_continuation_from_structure", must_not_evaluate)
    monkeypatch.setattr(runner, "evaluate_second_push_failure_from_structure", must_not_evaluate)

    assert generate_jianghe_signals(context, execution, quality_first_v2_config()) == []


def test_fast_runner_matches_baseline_runner_on_no_signal_fixture():
    context = _frame(pd.date_range("2026-01-01T00:15:00Z", periods=40, freq="15min"))
    execution = _frame(pd.date_range("2026-01-01T00:01:00Z", periods=120, freq="min"))
    cfg = JiangheRunnerConfig()

    assert generate_jianghe_signals_fast(context, execution, cfg) == generate_jianghe_signals(
        context, execution, cfg
    )
