import pytest

from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials


class FakeExchange:
    def __init__(self):
        self.events = []
        self.created_orders = []
        self.test_orders = []
        self.positions = []
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

    def set_sandbox_mode(self, enabled):
        self.events.append(("sandbox", enabled))

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


def test_gateway_enables_sandbox_before_any_market_call():
    gw, fake = gateway()

    assert fake.events == [("sandbox", True)]
    assert gw.status()["environment"] == "TESTNET"
    assert gw.status()["mainnet_orders_supported"] is False
    assert gw.status()["max_order_notional_usdt"] == 30.0


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
