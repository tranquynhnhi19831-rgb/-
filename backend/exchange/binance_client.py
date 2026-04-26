import ccxt


class BinanceClient:
    def __init__(self, api_key: str = "", secret: str = "", testnet: bool = True) -> None:
        options = {"defaultType": "future"}
        self.exchange = ccxt.binanceusdm({"apiKey": api_key, "secret": secret, "enableRateLimit": True, "options": options})
        if testnet:
            self.exchange.set_sandbox_mode(True)

    def test_connection(self) -> dict:
        try:
            markets = self.exchange.load_markets()
            return {"ok": True, "market_count": len(markets)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
