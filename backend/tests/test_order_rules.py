import pytest

from exchange.order_rules import MarketRules, OrderRuleError, normalize_order_quantity


def test_rounds_up_to_step():
    rules = MarketRules(symbol="BTC/USDT:USDT", min_amount=0.001, amount_step=0.001)
    assert normalize_order_quantity(0.0012, 60_000, rules) == 0.002


def test_enforces_min_notional():
    rules = MarketRules(
        symbol="BTC/USDT:USDT",
        min_amount=0.001,
        amount_step=0.001,
        min_notional=100.0,
    )
    # 0.001 BTC at 60k is only 60 USDT, so it must be raised to 0.002.
    assert normalize_order_quantity(0.001, 60_000, rules) == 0.002


def test_rejects_quantity_above_maximum():
    rules = MarketRules(
        symbol="BTC/USDT:USDT",
        min_amount=0.001,
        max_amount=0.01,
        amount_step=0.001,
    )
    with pytest.raises(OrderRuleError):
        normalize_order_quantity(0.02, 60_000, rules)


def test_rejects_non_positive_input():
    rules = MarketRules(symbol="BTC/USDT:USDT")
    with pytest.raises(OrderRuleError):
        normalize_order_quantity(0, 60_000, rules)
    with pytest.raises(OrderRuleError):
        normalize_order_quantity(0.001, 0, rules)
