from risk.risk_manager import RiskContext, RiskManager


BASE_CFG = {
    "margin_mode": "isolated",
    "max_leverage": 3,
    "risk_per_trade": 0.005,
    "max_margin_per_trade": 0.10,
    "max_daily_loss": 0.02,
    "max_trades_per_day": 3,
    "max_open_positions": 1,
    "max_consecutive_losses": 3,
    "enabled_symbols": ["BTC/USDT"],
}


def context(**overrides):
    data = {
        "equity": 100.0,
        "daily_pnl": 0.0,
        "trades_today": 0,
        "open_positions": 0,
        "consecutive_losses": 0,
        "day_start_equity": 100.0,
    }
    data.update(overrides)
    return RiskContext(**data)


def test_100u_baseline_risk_budget_is_half_usdt():
    manager = RiskManager()
    assert manager.risk_budget_usdt(BASE_CFG, 100.0) == 0.5


def test_blocks_at_two_percent_daily_loss():
    manager = RiskManager()
    allowed, reason = manager.check(
        BASE_CFG,
        context(equity=98.0, daily_pnl=-2.0),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert not allowed
    assert "每日最大亏损" in reason


def test_daily_loss_uses_start_of_day_equity_not_shrunken_current_equity():
    manager = RiskManager()
    decision = manager.evaluate(
        BASE_CFG,
        context(equity=98.01, daily_pnl=-1.99, day_start_equity=100.0),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert decision.allowed

    decision = manager.evaluate(
        BASE_CFG,
        context(equity=98.0, daily_pnl=-2.0, day_start_equity=100.0),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert not decision.allowed
    assert decision.code == "MAX_DAILY_LOSS_REACHED"


def test_blocks_leverage_above_configured_limit():
    manager = RiskManager()
    decision = manager.evaluate(
        BASE_CFG,
        context(),
        "BTC/USDT",
        rr=1.8,
        leverage=4,
        margin_ratio=0.05,
    )
    assert not decision.allowed
    assert decision.code == "MAX_LEVERAGE_EXCEEDED"


def test_daily_trade_limit_has_stable_reason_code():
    manager = RiskManager()
    decision = manager.evaluate(
        BASE_CFG,
        context(trades_today=3),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert not decision.allowed
    assert decision.code == "MAX_TRADES_PER_DAY_REACHED"
    assert "单日交易上限" in decision.message


def test_previous_day_loss_streak_does_not_deadlock_new_utc_day():
    manager = RiskManager()
    decision = manager.evaluate(
        BASE_CFG,
        context(trades_today=0, consecutive_losses=5),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert decision.allowed


def test_only_losses_possible_within_today_count_toward_cooldown():
    manager = RiskManager()
    decision = manager.evaluate(
        BASE_CFG,
        context(trades_today=1, consecutive_losses=5),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert decision.allowed


def test_three_same_day_consecutive_losses_block_rest_of_day():
    manager = RiskManager()
    cfg = {**BASE_CFG, "max_trades_per_day": 5}
    decision = manager.evaluate(
        cfg,
        context(trades_today=3, consecutive_losses=5),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert not decision.allowed
    assert decision.code == "MAX_CONSECUTIVE_LOSSES_REACHED"


def test_allows_valid_small_account_trade_context():
    manager = RiskManager()
    allowed, reason = manager.check(
        BASE_CFG,
        context(),
        "BTC/USDT",
        rr=1.8,
        leverage=1,
        margin_ratio=0.05,
    )
    assert allowed
    assert reason == "ok"
