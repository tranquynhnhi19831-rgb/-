import pytest

from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials


class FakeExchange:
    def __init__(self):
        self.events = []
        self.created_orders = []
        self.test_orders = []
        self.positions = []
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

    def fapiPrivatePostOrderTest(self, params):
        self.events.append(("order_test", params.copy()))
        self.test_orders.append(params.copy())
        return {}

    def create_order(self, symbol, type_, side, amount, price, params):
        self.events.append(("create_order", symbol, type_, side, amount, params.copy()))
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
    assert gw.status()["environment"] == "TESTNET"
    assert gw.status()["binance_mode"] == "DEMO_TRADING"
    assert gw.status()["official_rest_base"] == "https://demo-fapi.binance.com"
    assert gw.status()["mainnet_orders_supported"] is False
    assert gw.status()["max_order_notional_usdt"] == 30.0


def test_gateway_fails_closed_if_fapi_route_is_mainnet():
    fake = FakeExchange()
    fake.urls["api"]["fapiPrivate"] = "https://fapi.binance.com/fapi/v1"
    creds = TestnetCredentials("key", "secret")

    with pytest.raises(RuntimeError, match="unsafe Binance USD-M API route"):
        BinanceTestnetGateway(creds, exchange=fake)


def test_gateway_requires_modern_ccxt_demo_trading_capability():
    fake = FakeExchange()
    fake.enable_demo_trading = None
    creds = TestnetCredentials("key", "secret")

    with pytest.raises(RuntimeError, match="CCXT >= 4.5.6"):
        BinanceTestnetGateway(creds, exchange=fake)


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
    assert result["environment"] == "TESTNET"
    assert result["binance_mode"] == "DEMO_TRADING"
    assert len(fake.test_orders) == 1
    assert fake.created_orders == []
    assert fake.test_orders[0]["symbol"] == "BTCUSDT"
    assert fake.test_orders[0]["side"] == "BUY"


def test_actual_virtual_market_order_has_hard_notional_cap_and_confirmation():
    gw, fake = gateway()

    with pytest.raises(ValueError, match="hard cap"):
        gw.place_market_order(
            symbol="BTC/USDT",
            side="BUY",
            target_notional_usdt=30.01,
            client_order_id="jh_big",
            confirm="PLACE_TESTNET_ORDER",
        )

    with pytest.raises(RuntimeError, match="PLACE_TESTNET_ORDER"):
        gw.place_market_order(
            symbol="BTC/USDT",
            side="BUY",
            target_notional_usdt=5,
            client_order_id="jh_no_confirm",
            confirm=None,
        )

    result = gw.place_market_order(
        symbol="BTC/USDT",
        side="BUY",
        target_notional_usdt=5,
        client_order_id="jh_open_1",
        confirm="PLACE_TESTNET_ORDER",
    )

    assert result["virtual_money_only"] is True
    assert result["order"]["client_order_id"] == "jh_open_1"
    assert fake.created_orders[0][1]["newClientOrderId"] == "jh_open_1"


def test_exchange_minimum_cannot_round_position_above_100u_profile_cap():
    fake = FakeExchange()
    market = fake.markets["BTC/USDT:USDT"]
    market["info"]["filters"][0] = {
        "filterType": "MARKET_LOT_SIZE",
        "minQty": "0.500",
        "maxQty": "100",
        "stepSize": "0.500",
    }
    market["limits"]["amount"]["min"] = 0.5
    gw, _ = gateway(fake)

    with pytest.raises(ValueError, match="minimum quantity/notional"):
        gw.place_market_order(
            symbol="BTC/USDT",
            side="BUY",
            target_notional_usdt=5,
            client_order_id="jh_filter_cap",
            confirm="PLACE_TESTNET_ORDER",
        )

    assert fake.created_orders == []


def test_invalid_side_and_client_order_id_are_rejected_before_order_creation():
    gw, fake = gateway()

    with pytest.raises(ValueError, match="side must be BUY or SELL"):
        gw.place_market_order(
            symbol="BTC/USDT",
            side="LONG",
            target_notional_usdt=5,
            client_order_id="jh_bad_side",
            confirm="PLACE_TESTNET_ORDER",
        )

    with pytest.raises(ValueError, match="client_order_id"):
        gw.place_market_order(
            symbol="BTC/USDT",
            side="BUY",
            target_notional_usdt=5,
            client_order_id="bad id with spaces",
            confirm="PLACE_TESTNET_ORDER",
        )

    assert fake.created_orders == []


def test_close_position_is_reduce_only_and_opposite_side():
    gw, fake = gateway()
    fake.positions = [
        {
            "symbol": "BTC/USDT:USDT",
            "side": "long",
            "contracts": 0.05,
            "entryPrice": 99.0,
            "markPrice": 100.0,
            "unrealizedPnl": 0.05,
            "leverage": 3,
        }
    ]

    result = gw.close_position(
        symbol="BTC/USDT",
        client_order_id="jh_close_1",
        confirm="CLOSE_TESTNET_POSITION",
    )

    assert result["reduce_only"] is True
    created, params = fake.created_orders[0]
    assert created["side"] == "sell"
    assert params["reduceOnly"] is True


def test_close_position_refuses_ambiguous_or_missing_position():
    gw, _ = gateway()

    with pytest.raises(RuntimeError, match="exactly one active Testnet position"):
        gw.close_position(
            symbol="BTC/USDT",
            client_order_id="jh_close_none",
            confirm="CLOSE_TESTNET_POSITION",
        )
