from __future__ import annotations

import ccxt

from exchange.order_rules import MarketRules, normalize_order_quantity


class BinanceClient:
    """Small Binance USDT-M adapter used by the trading engine.

    S1 intentionally exposes only public-market inspection and order preview
    helpers. It does not add any new live order entrypoint.
    """

    def __init__(
        self,
        api_key: str = "",
        secret: str = "",
        testnet: bool = True,
        exchange=None,
    ) -> None:
        if exchange is not None:
            self.exchange = exchange
            return

        options = {"defaultType": "future"}
        self.exchange = ccxt.binanceusdm(
            {
                "apiKey": api_key,
                "secret": secret,
                "enableRateLimit": True,
                "options": options,
            }
        )
        if testnet:
            self.exchange.set_sandbox_mode(True)

    def load_markets(self, reload: bool = False) -> dict:
        return self.exchange.load_markets(reload)

    def resolve_symbol(self, symbol: str) -> str:
        markets = self.load_markets()
        raw = symbol.strip().upper()
        if raw in markets:
            return raw

        if "/" not in raw and raw.endswith("USDT"):
            raw = f"{raw[:-4]}/USDT"

        if "/" in raw and ":" not in raw:
            base, quote = raw.split("/", 1)
            futures_symbol = f"{base}/{quote}:{quote}"
            if futures_symbol in markets:
                return futures_symbol
            if raw in markets:
                return raw

        raise ValueError(f"unsupported Binance USDT-M symbol: {symbol}")

    def validate_usdm_universe(self, symbols) -> dict:
        """Verify every configured symbol resolves to an active USDT perpetual.

        The code-level market-cap universe is intentionally fixed for research
        reproducibility, but exchange listings can change. This runtime check
        prevents the scanner from silently operating with a partial universe.
        """
        markets = self.load_markets()
        items = []
        all_ok = True

        for requested in symbols:
            try:
                resolved = self.resolve_symbol(requested)
                market = markets[resolved]
                info = market.get("info", {}) or {}
                status = str(info.get("status") or "").upper()
                active = market.get("active") is not False and status not in {
                    "CLOSE",
                    "DELIVERED",
                    "PRE_DELIVERING",
                    "DELIVERING",
                    "SETTLING",
                }
                is_perpetual = bool(
                    market.get("swap") is True
                    or str(market.get("type") or "").lower() == "swap"
                    or str(info.get("contractType") or "").upper() == "PERPETUAL"
                )
                quote_ok = str(market.get("quote") or "USDT").upper() == "USDT"
                linear_ok = market.get("linear") is not False
                ok = bool(active and is_perpetual and quote_ok and linear_ok)
                all_ok = all_ok and ok
                items.append(
                    {
                        "requested_symbol": requested,
                        "resolved_symbol": resolved,
                        "exchange_id": market.get("id"),
                        "status": status or ("TRADING" if active else "UNKNOWN"),
                        "active": bool(active),
                        "perpetual": bool(is_perpetual),
                        "linear": bool(linear_ok),
                        "quote_usdt": bool(quote_ok),
                        "ok": ok,
                    }
                )
            except Exception as exc:
                all_ok = False
                items.append(
                    {
                        "requested_symbol": requested,
                        "resolved_symbol": None,
                        "exchange_id": None,
                        "status": "UNAVAILABLE",
                        "active": False,
                        "perpetual": False,
                        "linear": False,
                        "quote_usdt": False,
                        "ok": False,
                        "error": str(exc),
                    }
                )

        return {"ok": all_ok, "count": len(items), "markets": items}

    @staticmethod
    def _filter(info: dict, filter_type: str) -> dict:
        for item in info.get("filters", []) or []:
            if item.get("filterType") == filter_type:
                return item
        return {}

    @staticmethod
    def _as_float(value) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def get_market_rules(self, symbol: str) -> MarketRules:
        resolved = self.resolve_symbol(symbol)
        market = self.load_markets()[resolved]
        info = market.get("info", {}) or {}

        lot = self._filter(info, "MARKET_LOT_SIZE") or self._filter(info, "LOT_SIZE")
        price_filter = self._filter(info, "PRICE_FILTER")
        notional_filter = self._filter(info, "NOTIONAL") or self._filter(info, "MIN_NOTIONAL")
        limits = market.get("limits", {}) or {}

        amount_limits = limits.get("amount", {}) or {}
        cost_limits = limits.get("cost", {}) or {}

        min_amount = self._as_float(lot.get("minQty")) or self._as_float(amount_limits.get("min"))
        max_amount = self._as_float(lot.get("maxQty")) or self._as_float(amount_limits.get("max"))
        amount_step = self._as_float(lot.get("stepSize"))
        min_notional = (
            self._as_float(notional_filter.get("minNotional"))
            or self._as_float(notional_filter.get("notional"))
            or self._as_float(cost_limits.get("min"))
        )
        price_tick = self._as_float(price_filter.get("tickSize"))

        return MarketRules(
            symbol=resolved,
            min_amount=min_amount,
            max_amount=max_amount,
            amount_step=amount_step,
            min_notional=min_notional,
            price_tick=price_tick,
        )

    def fetch_last_price(self, symbol: str) -> float:
        resolved = self.resolve_symbol(symbol)
        ticker = self.exchange.fetch_ticker(resolved)
        price = ticker.get("last") or ticker.get("close")
        if price is None or float(price) <= 0:
            raise ValueError(f"no valid last price returned for {resolved}")
        return float(price)

    def preview_market_order(
        self,
        symbol: str,
        target_notional_usdt: float,
        price: float | None = None,
    ) -> dict:
        """Calculate a Binance-valid market quantity without placing an order."""
        if target_notional_usdt <= 0:
            raise ValueError("target_notional_usdt must be greater than zero")

        resolved = self.resolve_symbol(symbol)
        market_price = float(price) if price is not None else self.fetch_last_price(resolved)
        rules = self.get_market_rules(resolved)
        requested_quantity = target_notional_usdt / market_price
        normalized_quantity = normalize_order_quantity(requested_quantity, market_price, rules)

        normalized_quantity = float(self.exchange.amount_to_precision(resolved, normalized_quantity))
        actual_notional = normalized_quantity * market_price

        if rules.min_notional and actual_notional + 1e-9 < rules.min_notional:
            normalized_quantity = normalize_order_quantity(
                normalized_quantity + (rules.amount_step or normalized_quantity * 1e-9),
                market_price,
                rules,
            )
            normalized_quantity = float(self.exchange.amount_to_precision(resolved, normalized_quantity))
            actual_notional = normalized_quantity * market_price

        return {
            "symbol": resolved,
            "price": market_price,
            "requested_notional_usdt": target_notional_usdt,
            "quantity": normalized_quantity,
            "actual_notional_usdt": actual_notional,
            "rules": rules.__dict__,
            "places_order": False,
        }

    def test_connection(self) -> dict:
        try:
            markets = self.load_markets()
            sample_rules = self.get_market_rules("BTC/USDT")
            return {
                "ok": True,
                "market_count": len(markets),
                "sample_market_rules": sample_rules.__dict__,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
