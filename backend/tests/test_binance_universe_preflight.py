from exchange.binance_client import BinanceClient


class FakeMarketsExchange:
    def __init__(self):
        self.markets = {
            "BTC/USDT:USDT": {
                "id": "BTCUSDT",
                "symbol": "BTC/USDT:USDT",
                "active": True,
                "swap": True,
                "linear": True,
                "quote": "USDT",
                "info": {"status": "TRADING", "contractType": "PERPETUAL"},
            },
            "HYPE/USDT:USDT": {
                "id": "HYPEUSDT",
                "symbol": "HYPE/USDT:USDT",
                "active": True,
                "swap": True,
                "linear": True,
                "quote": "USDT",
                "info": {"status": "TRADING", "contractType": "PERPETUAL"},
            },
        }

    def load_markets(self, reload=False):
        return self.markets


def test_universe_preflight_requires_active_linear_usdt_perpetuals():
    client = BinanceClient(exchange=FakeMarketsExchange())

    result = client.validate_usdm_universe(("BTC/USDT", "HYPE/USDT"))

    assert result["ok"] is True
    assert result["count"] == 2
    assert all(item["ok"] for item in result["markets"])
    assert result["markets"][1]["exchange_id"] == "HYPEUSDT"


def test_universe_preflight_reports_missing_contract_instead_of_silently_skipping():
    client = BinanceClient(exchange=FakeMarketsExchange())

    result = client.validate_usdm_universe(("BTC/USDT", "TRX/USDT"))

    assert result["ok"] is False
    missing = [item for item in result["markets"] if item["requested_symbol"] == "TRX/USDT"][0]
    assert missing["status"] == "UNAVAILABLE"
    assert missing["ok"] is False
