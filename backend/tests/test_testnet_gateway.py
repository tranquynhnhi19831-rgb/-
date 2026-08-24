import ccxt
import pytest

from exchange.testnet_gateway import (
    AmbiguousDemoOrderState,
    BinanceTestnetGateway,
    TestnetCredentials,
    _proxy_config_from_env,
)


class FakeExchange:
    def __init__(self):
        self.events = []
        self.created_orders = []
        self.test_orders = []
        self.orders_by_client = {}
        self.position_mode_dual = False
        self.timeout_after_create = False
        self.timeout_without_create = False
        self.positions = [
            {
                "symbol": "BTC/USDT:USDT",
                "side": None,
                "contracts": 0.0,
                "entryPrice": 0.0,
                "markPrice": 100.0,
                "unrealizedPnl": 0.0,
                "leverage": 3,
                "marginMode": "isolated",
                "info": {"marginType": "isolated", "leverage": "3"},
            }
        ]
        self.urls = {
            "api": {
                "fapiPublic": "https://demo-fapi.binance.com/fapi/v1",
                "fapiPrivate": "https://demo-fapi.binance.com/fapi/v1",
                "fapiPublicV2": "https://demo-fapi.binance.com/fapi/v2",
                "fapiPrivateV2": "https://demo-fapi.binance.com/fapi/v2",
                "fapiPrivateV3": "https://demo-fapi.binance.com/fapi/v3",
            }
        }
        self.markets = {
            "BTC/USDT:USDT": {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT:USDT",
                "info": {
                    "filters": [
                        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                    ]
                },
                "limits": {"amount": {"min": 0.001, "max": 100}, "cost": {"min": 5}},
            }
        }

    def enable_demo_trading(self, enabled):
        self.events.append(("demo_trading", enabled))

    def load_markets(self, reload=False):
        self.events.append(("load_markets", reload))
        return self.markets

    def market(self, symbol):
        self.events.append(("market", symbol))
        return self.markets[symbol]

    def fetch_ticker(self, symbol):
        self.events.append(("fetch_ticker", symbol))
        return {"last": 100.0}

    def amount_to_precision(self, symbol, amount):
        self.events.append(("amount_to_precision", symbol, amount))
        return f"{float(amount):.3f}"

    def fetch_balance(self):
        self.events.append(("fetch_balance",))
        return {"USDT": {"free": 100.0, "total": 100.0}}

    def fetch_positions(self, symbols=None):
        self.events.append(("fetch_positions", symbols))
        return self.positions

    def fetch_open_orders(self):
        self.events.append(("fetch_open_orders",))
        return []

    def fapiPrivateGetPositionSideDual(self, params):
        self.events.append(("position_mode", params.copy()))
        return {"dualSidePosition": self.position_mode_dual}

    def fapiPrivateGetOrder(self, params):
        self.events.append(("get_order_by_client", params.copy()))
        client_id = params.get("origClientOrderId")
        raw = self.orders_by_client.get(client_id)
        if raw is None:
            raise ccxt.OrderNotFound("binanceusdm -2013 Order does not exist")
        return raw.copy()

    def fapiPrivatePostOrderTest(self, params):
        self.events.append(("order_test", params.copy()))
        self.test_orders.append(params.copy())
        return {}

    def _store_raw_order(self, order):
        raw = {
            "orderId": order["id"],
            "clientOrderId": order["clientOrderId"],
            "symbol": "BTCUSDT",
            "type": str(order["type"]).upper(),
            "side": str(order["side"]).upper(),
            "status": str(order["status"]).upper(),
            "origQty": str(order["amount"]),
            "executedQty": str(order["filled"]),
            "avgPrice": str(order["average"] or 0),
            "price": "0",
            "updateTime": order["timestamp"],
        }
        self.orders_by_client[order["clientOrderId"]] = raw

    def create_order(self, symbol, type_, side, amount, price, params):
        self.events.append(("create_order", symbol, type_, side, amount, params.copy()))
        if self.timeout_without_create:
            raise ccxt.RequestTimeout("simulated timeout before exchange accepted order")
        order = {
            "id": str(len(self.created_orders) + 1),
            "clientOrderId": params.get("newClientOrderId"),
            "symbol": symbol,
            "type": type_,
            "side": side,
            "status": "closed",
            "amount": float(amount),
            "filled": float(amount),
            "remaining": 0.0,
            "average": 100.0,
            "price": None,
            "timestamp": 1,
        }
        self.created_orders.append((order, params.copy()))
        self._store_raw_order(order)
        if self.timeout_after_create:
            raise ccxt.RequestTimeout("simulated response timeout after exchange accepted order")
        return order

    def fetch_order(self, order_id, symbol):
        self.events.append(("fetch_order", order_id, symbol))
        return {"id": order_id, "symbol": symbol, "status": "open"}

    def cancel_order(self, order_id, symbol):
        self.events.append(("cancel_order", order_id, symbol))
        return {"id": order_id, "symbol": symbol, "status": "canceled"}


def gateway(fake=None, configured=True):
    exchange = fake or FakeExchange()
    creds = TestnetCredentials("key" if configured else "", "secret" if configured else "")
    return BinanceTestnetGateway(creds, exchange=exchange), exchange


def test_gateway_enables_demo_trading_before_any_market_call():
    gw, fake = gateway()
    assert fake.events == [("demo_trading", True)]
    status = gw.status()
    assert status["environment"] == "TESTNET"
    assert status["binance_mode"] == "DEMO_TRADING"
    assert status["official_rest_base"] == "https://demo-fapi.binance.com"
    assert status["mainnet_orders_supported"] is False
    assert status["max_order_notional_usdt"] == 30.0
    assert status["max_leverage"] == 3
    assert "NO_BLIND_CREATE_RETRY" in status["idempotency"]


def test_gateway_fails_closed_if_fapi_route_is_mainnet():
    fake = FakeExchange()
    fake.urls["api"]["fapiPrivate"] = "https://fapi.binance.com/fapi/v1"
    with pytest.raises(RuntimeError, match="unsafe Binance USD-M API route"):
        BinanceTestnetGateway(TestnetCredentials("key", "secret"), exchange=fake)


def test_gateway_requires_modern_ccxt_demo_trading_capability():
    fake = FakeExchange()
    fake.enable_demo_trading = None
    with pytest.raises(RuntimeError, match="CCXT >= 4.5.6"):
        BinanceTestnetGateway(TestnetCredentials("key", "secret"), exchange=fake)


def test_private_calls_require_server_side_testnet_credentials():
    gw, _ = gateway(configured=False)
    with pytest.raises(RuntimeError, match="credentials are not configured"):
        gw.authenticated_health()


def test_signed_order_test_creates_no_order_and_requires_explicit_confirmation():
    gw, fake = gateway()
    with pytest.raises(RuntimeError, match="TESTNET_ORDER_TEST"):
        gw.test_market_order(
            symbol="BTC/USDT", side="BUY", target_notional_usdt=5, client_order_id="jh_test_1", confirm=None
        )
    result = gw.test_market_order(
        symbol="BTC/USDT",
        side="BUY",
        target_notional_usdt=5,
        client_order_id="jh_test_1",
        confirm="TESTNET_ORDER_TEST",
    )
    assert result["creates_order"] is False
    assert len(fake.test_orders) == 1
    assert fake.created_orders == []
    assert fake.test_orders[0]["symbol"] == "BTCUSDT"
    assert fake.test_orders[0]["side"] == "BUY"


def test_execution_preflight_requires_one_way_isolated_and_leverage_cap():
    gw, fake = gateway()
    result = gw.execution_account_preflight(symbol="BTC/USDT")
    assert result["position_mode"] == "ONE_WAY"
    assert result["margin_mode"] == "isolated"
    assert result["leverage"] == 3
    assert result["mutated_settings"] is False

    fake.position_mode_dual = True
    with pytest.raises(RuntimeError, match="HEDGE_MODE_NOT_ALLOWED"):
        gw.execution_account_preflight(symbol="BTC/USDT")

    fake.position_mode_dual = False
    fake.positions[0]["marginMode"] = "cross"
    fake.positions[0]["info"]["marginType"] = "cross"
    with pytest.raises(RuntimeError, match="MARGIN_MODE_NOT_ISOLATED"):
        gw.execution_account_preflight(symbol="BTC/USDT")

    fake.positions[0]["marginMode"] = "isolated"
    fake.positions[0]["info"]["marginType"] = "isolated"
    fake.positions[0]["leverage"] = 4
    with pytest.raises(RuntimeError, match="MAX_LEVERAGE_EXCEEDED"):
        gw.execution_account_preflight(symbol="BTC/USDT")


def test_actual_virtual_market_order_has_hard_notional_cap_and_confirmation():
    gw, fake = gateway()
    with pytest.raises(ValueError, match="hard cap"):
        gw.place_market_order(
            symbol="BTC/USDT", side="BUY", target_notional_usdt=30.01,
            client_order_id="jh_big", confirm="PLACE_TESTNET_ORDER",
        )
    with pytest.raises(RuntimeError, match="PLACE_TESTNET_ORDER"):
        gw.place_market_order(
            symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
            client_order_id="jh_no_confirm", confirm=None,
        )
    result = gw.place_market_order(
        symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
        client_order_id="jh_open_1", confirm="PLACE_TESTNET_ORDER",
    )
    assert result["virtual_money_only"] is True
    assert result["idempotent_replay"] is False
    assert result["order"]["client_order_id"] == "jh_open_1"
    assert len(fake.created_orders) == 1


def test_same_client_order_id_is_idempotent_and_does_not_create_twice():
    gw, fake = gateway()
    first = gw.place_market_order(
        symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
        client_order_id="jh_idem_1", confirm="PLACE_TESTNET_ORDER",
    )
    second = gw.place_market_order(
        symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
        client_order_id="jh_idem_1", confirm="PLACE_TESTNET_ORDER",
    )
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(fake.created_orders) == 1
    assert second["order"]["id"] == first["order"]["id"]


def test_timeout_after_exchange_acceptance_recovers_by_client_id_without_retrying_create():
    fake = FakeExchange()
    fake.timeout_after_create = True
    gw, _ = gateway(fake)
    result = gw.place_market_order(
        symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
        client_order_id="jh_timeout_recovered", confirm="PLACE_TESTNET_ORDER",
    )
    assert result["recovered_after_ambiguous_create"] is True
    assert result["order"]["client_order_id"] == "jh_timeout_recovered"
    assert len(fake.created_orders) == 1
    create_events = [event for event in fake.events if event[0] == "create_order"]
    assert len(create_events) == 1


def test_timeout_with_no_visible_exchange_order_fails_ambiguous_and_never_blind_retries():
    fake = FakeExchange()
    fake.timeout_without_create = True
    gw, _ = gateway(fake)
    with pytest.raises(AmbiguousDemoOrderState, match="AMBIGUOUS_ORDER_STATE"):
        gw.place_market_order(
            symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
            client_order_id="jh_timeout_unknown", confirm="PLACE_TESTNET_ORDER",
        )
    create_events = [event for event in fake.events if event[0] == "create_order"]
    assert len(create_events) == 1


def test_client_id_reuse_with_different_side_fails_closed():
    gw, fake = gateway()
    gw.place_market_order(
        symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
        client_order_id="jh_collision", confirm="PLACE_TESTNET_ORDER",
    )
    with pytest.raises(RuntimeError, match="different side"):
        gw.place_market_order(
            symbol="BTC/USDT", side="SELL", target_notional_usdt=5,
            client_order_id="jh_collision", confirm="PLACE_TESTNET_ORDER",
        )
    assert len(fake.created_orders) == 1


def test_exchange_minimum_cannot_round_position_above_100u_profile_cap():
    fake = FakeExchange()
    market = fake.markets["BTC/USDT:USDT"]
    market["info"]["filters"][0] = {
        "filterType": "MARKET_LOT_SIZE", "minQty": "0.500", "maxQty": "100", "stepSize": "0.500",
    }
    market["limits"]["amount"]["min"] = 0.5
    gw, _ = gateway(fake)
    with pytest.raises(ValueError, match="minimum quantity/notional"):
        gw.place_market_order(
            symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
            client_order_id="jh_filter_cap", confirm="PLACE_TESTNET_ORDER",
        )
    assert fake.created_orders == []


def test_invalid_side_and_client_order_id_are_rejected_before_order_creation():
    gw, fake = gateway()
    with pytest.raises(ValueError, match="side must be BUY or SELL"):
        gw.place_market_order(
            symbol="BTC/USDT", side="LONG", target_notional_usdt=5,
            client_order_id="jh_bad_side", confirm="PLACE_TESTNET_ORDER",
        )
    with pytest.raises(ValueError, match="client_order_id"):
        gw.place_market_order(
            symbol="BTC/USDT", side="BUY", target_notional_usdt=5,
            client_order_id="bad id with spaces", confirm="PLACE_TESTNET_ORDER",
        )
    assert fake.created_orders == []


def test_close_position_is_reduce_only_and_opposite_side():
    gw, fake = gateway()
    fake.positions = [
        {
            "symbol": "BTC/USDT:USDT", "side": "long", "contracts": 0.05,
            "entryPrice": 99.0, "markPrice": 100.0, "unrealizedPnl": 0.05,
            "leverage": 3, "marginMode": "isolated", "info": {"marginType": "isolated", "leverage": "3"},
        }
    ]
    result = gw.close_position(
        symbol="BTC/USDT", client_order_id="jh_close_1", confirm="CLOSE_TESTNET_POSITION",
    )
    assert result["reduce_only"] is True
    created, params = fake.created_orders[0]
    assert created["side"] == "sell"
    assert params["reduceOnly"] is True


def test_close_position_refuses_ambiguous_or_missing_active_position():
    gw, fake = gateway()
    # Keep the zero-position config so execution preflight is valid, but there is
    # no active contract to reduce.
    with pytest.raises(RuntimeError, match="exactly one active Testnet position"):
        gw.close_position(
            symbol="BTC/USDT", client_order_id="jh_close_none", confirm="CLOSE_TESTNET_POSITION",
        )
    assert fake.created_orders == []


def test_proxy_config_from_env_normalizes_one_sided_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    assert _proxy_config_from_env() == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }


def test_real_ccxt_factory_receives_explicit_runtime_proxy(monkeypatch):
    fake = FakeExchange()
    captured = {}
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7890")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    def factory(config):
        captured.update(config)
        return fake

    monkeypatch.setattr("exchange.testnet_gateway.ccxt.binanceusdm", factory)
    gw = BinanceTestnetGateway(TestnetCredentials("key", "secret"))
    assert captured["proxies"] == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    assert gw.status()["proxy_configured"] is True
    assert fake.events == [("demo_trading", True)]
