from backtest.jianghe_scored_runner import ScoredMultiTimeframeRunnerConfig


def test_v5_default_profile_identity_is_unchanged():
    cfg = ScoredMultiTimeframeRunnerConfig()
    assert cfg.execution_timeframe_label == "1m"
    assert cfg.setup_version == "V5_SCORED_MTF_PULLBACK"
    assert cfg.setup_name == "TREND_PULLBACK_EVENT_V5_SCORED_MTF"
    assert cfg.signal_cooldown_bars == 6


def test_v6_profile_changes_only_explicit_execution_metadata_and_cooldown():
    cfg = ScoredMultiTimeframeRunnerConfig(
        signal_cooldown_bars=1,
        execution_timeframe_label="5m",
        setup_version="V6_5M_SCORED_MTF_PULLBACK",
        setup_name="TREND_PULLBACK_EVENT_V6_5M_SCORED_MTF",
    )
    cfg.validate()
    assert cfg.execution_timeframe_label == "5m"
    assert cfg.min_quality_score == 0.55
    assert cfg.min_macro_efficiency == 0.18
    assert cfg.min_context_efficiency == 0.22
