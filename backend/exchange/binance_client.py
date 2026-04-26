from __future__ import annotations

import ccxt


class BinanceClient:
    def __init__(self, api_key: str = "", secret: str = "", testnet: bool = True) -> None:
        options = {"defaultType": "future"}
        self.exchange = ccxt.binanceusdm(
            {
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True,
                "options": options,
            }
        )
        self.exchange.set_sandbox_mode(testnet)

    def test_connection(self) -> dict:
        try:
            self.exchange.load_markets()
            bal = self.exchange.fetch_balance()
            usdt = float(bal.get("USDT", {}).get("free", 0) or 0)
            return {"ok": True, "usdt_free": usdt}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 300):
        return self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_futures_account(self) -> dict:
        bal = self.exchange.fetch_balance()
        usdt_wallet = float((bal.get("USDT") or {}).get("total", 0) or 0)
        usdt_free = float((bal.get("USDT") or {}).get("free", 0) or 0)
        return {"wallet": usdt_wallet, "free": usdt_free}

    def fetch_positions(self) -> list[dict]:
        try:
            return self.exchange.fetch_positions()
        except Exception:
            return []

    def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        try:
            return self.exchange.fetch_open_orders(symbol)
        except Exception:
            return []

    def market(self, symbol: str) -> dict:
        return self.exchange.market(symbol)

    def create_order(self, symbol: str, side: str, amount: float, stop_loss: float, take_profit: float):
        order_side = "buy" if side == "long" else "sell"
        return self.exchange.create_order(symbol=symbol, type="market", side=order_side, amount=amount, params={"reduceOnly": False, "stopLossPrice": stop_loss, "takeProfitPrice": take_profit})
