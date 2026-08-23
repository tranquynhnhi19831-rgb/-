from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import ccxt

from exchange.binance_client import BinanceClient

TESTNET_ENVIRONMENT = "TESTNET"
BINANCE_USDM_DEMO_REST_BASE = "https://demo-fapi.binance.com"
# 100U * 10% max margin * 3x leverage = 30U maximum position notional.
MAX_TESTNET_ORDER_NOTIONAL_USDT = 30.0
CLIENT_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


def _proxy_config_from_env() -> dict[str, str]:
    """Build explicit CCXT requests proxies from standard environment variables.

    CCXT does not rely on requests' environment proxy discovery by default, so
    the private Demo gateway must pass proxies explicitly when the runtime has
    HTTP_PROXY/HTTPS_PROXY configured. This keeps local Binance Demo access on
    the same approved network path already used by the host environment.
    """

    http_proxy = (os.getenv("HTTP_PROXY") or os.getenv("http_proxy") or "").strip()
    https_proxy = (os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or "").strip()

    if not http_proxy and not https_proxy:
        return {}
    if not http_proxy:
        http_proxy = https_proxy
    if not https_proxy:
        https_proxy = http_proxy
    return {"http": http_proxy, "https": https_proxy}


@dataclass(frozen=True)
class TestnetCredentials:
    api_key: str
    secret: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.secret)

    @classmethod
    def from_env(cls) -> "TestnetCredentials":
        return cls(
            api_key=os.getenv("BINANCE_TESTNET_API_KEY", "").strip(),
            secret=os.getenv("BINANCE_TESTNET_SECRET", "").strip(),
        )


class BinanceTestnetGateway:
    """Private Binance USD-M Demo/Testnet gateway with no Mainnet execution path.

    Binance's current USD-M testing environment is exposed as Demo Trading.
    S7 deliberately has no Mainnet base-url switch. The gateway enables CCXT
    Demo Trading before any market/private call and verifies any active fapi
    REST URLs point at Binance's documented demo host.
    """

    environment = TESTNET_ENVIRONMENT

    def __init__(
        self,
        credentials: TestnetCredentials,
        *,
        exchange: Any | None = None,
        max_order_notional_usdt: float = MAX_TESTNET_ORDER_NOTIONAL_USDT,
    ) -> None:
        if max_order_notional_usdt <= 0:
            raise ValueError("max_order_notional_usdt must be > 0")
        self.credentials = credentials
        self.max_order_notional_usdt = float(max_order_notional_usdt)

        if exchange is None:
            exchange_config: dict[str, Any] = {
                "apiKey": credentials.api_key,
                "secret": credentials.secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
            proxies = _proxy_config_from_env()
            if proxies:
                exchange_config["proxies"] = proxies
            exchange = ccxt.binanceusdm(exchange_config)
        self.exchange = exchange
        self._enable_demo_trading()
        self._assert_demo_fapi_urls()
        self.market = BinanceClient(exchange=self.exchange)

    def _enable_demo_trading(self) -> None:
        # Binance deprecated the old Futures sandbox. Modern CCXT exposes the
        # replacement environment through enable_demo_trading(True).
        enable_demo = getattr(self.exchange, "enable_demo_trading", None)
        if enable_demo is None:
            raise RuntimeError(
                "installed CCXT does not support Binance Demo Trading; CCXT >= 4.5.6 is required"
            )
        # Must happen before any exchange request.
        enable_demo(True)

    def _assert_demo_fapi_urls(self) -> None:
        """Fail closed if CCXT leaves an active USD-M REST URL on Mainnet."""
        urls = getattr(self.exchange, "urls", None)
        if not isinstance(urls, dict):
            return
        api_urls = urls.get("api")
        if not isinstance(api_urls, dict):
            return

        checked = 0
        for key, value in api_urls.items():
            if "fapi" not in str(key).lower() or not isinstance(value, str):
                continue
            checked += 1
            if "demo-fapi.binance.com" not in value:
                raise RuntimeError(
                    f"unsafe Binance USD-M API route after enabling Demo Trading: {key}={value}"
                )

        # Current CCXT exposes fapi keys. If a future SDK hides them, network
        # acceptance still verifies the host, but do not fail injected test doubles.
        if checked == 0 and self.exchange.__class__.__module__.startswith("ccxt"):
            raise RuntimeError("unable to verify Binance Demo Trading USD-M REST routes")

    @classmethod
    def from_env(cls) -> "BinanceTestnetGateway":
        return cls(TestnetCredentials.from_env())

    def _require_credentials(self) -> None:
        if not self.credentials.configured:
            raise RuntimeError(
                "Binance Testnet/Demo credentials are not configured; set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET"
            )

    @staticmethod
    def _confirm(value: str | None, expected: str) -> None:
        if value != expected:
            raise RuntimeError(f"explicit confirmation required: {expected}")

    @staticmethod
    def _validate_side(side: str) -> str:
        normalized = side.strip().upper()
        if normalized not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        return normalized

    @staticmethod
    def _validate_client_order_id(client_order_id: str) -> str:
        value = client_order_id.strip()
        if not CLIENT_ORDER_ID_RE.fullmatch(value):
            raise ValueError("client_order_id must be 1-36 chars using letters, digits, _ or -")
        return value

    def _preview(self, symbol: str, target_notional_usdt: float) -> dict:
        if target_notional_usdt <= 0:
            raise ValueError("target_notional_usdt must be > 0")
        if target_notional_usdt > self.max_order_notional_usdt + 1e-9:
            raise ValueError(
                f"S7 Testnet requested notional exceeds hard cap of {self.max_order_notional_usdt:.2f} USDT"
            )

        preview = self.market.preview_market_order(symbol, target_notional_usdt)
        # Exchange filters can round a tiny request upward to minQty/minNotional.
        # Never allow that normalization to silently violate the 100U risk cap.
        actual_notional = float(preview["actual_notional_usdt"])
        if actual_notional > self.max_order_notional_usdt + 1e-9:
            raise ValueError(
                "Binance minimum quantity/notional would exceed the S7 hard position cap: "
                f"{actual_notional:.4f} > {self.max_order_notional_usdt:.2f} USDT"
            )
        return preview

    def status(self) -> dict:
        """Local status only; does not make a network call."""
        return {
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "official_rest_base": BINANCE_USDM_DEMO_REST_BASE,
            "credentials_configured": self.credentials.configured,
            "demo_trading_required": True,
            "mainnet_orders_supported": False,
            "max_order_notional_usdt": self.max_order_notional_usdt,
            "proxy_configured": bool(_proxy_config_from_env()),
        }

    def authenticated_health(self) -> dict:
        """Verify Demo/Testnet credentials with a read-only private account request."""
        self._require_credentials()
        balance = self.exchange.fetch_balance()
        usdt = balance.get("USDT", {}) if isinstance(balance, dict) else {}
        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "usdt_free": float(usdt.get("free") or 0.0),
            "usdt_total": float(usdt.get("total") or 0.0),
        }

    def account_snapshot(self) -> dict:
        self._require_credentials()
        balance = self.exchange.fetch_balance()
        positions = self.exchange.fetch_positions()
        open_orders = self.exchange.fetch_open_orders()
        usdt = balance.get("USDT", {}) if isinstance(balance, dict) else {}

        active_positions = []
        for position in positions or []:
            contracts = float(position.get("contracts") or 0.0)
            if abs(contracts) <= 0:
                continue
            active_positions.append(
                {
                    "symbol": position.get("symbol"),
                    "side": position.get("side"),
                    "contracts": contracts,
                    "entry_price": float(position.get("entryPrice") or 0.0),
                    "mark_price": float(position.get("markPrice") or 0.0),
                    "unrealized_pnl": float(position.get("unrealizedPnl") or 0.0),
                    "leverage": float(position.get("leverage") or 0.0),
                }
            )

        return {
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "usdt_free": float(usdt.get("free") or 0.0),
            "usdt_total": float(usdt.get("total") or 0.0),
            "positions": active_positions,
            "open_orders": [self._safe_order(order) for order in (open_orders or [])],
        }

    def test_market_order(
        self,
        *,
        symbol: str,
        side: str,
        target_notional_usdt: float,
        client_order_id: str,
        confirm: str | None,
    ) -> dict:
        """Call Binance `/fapi/v1/order/test`; validates signature but creates no order."""
        self._require_credentials()
        self._confirm(confirm, "TESTNET_ORDER_TEST")
        side_value = self._validate_side(side)
        client_id = self._validate_client_order_id(client_order_id)
        preview = self._preview(symbol, target_notional_usdt)
        resolved = preview["symbol"]
        market = self.exchange.market(resolved)
        raw_symbol = market.get("id") or resolved.replace("/", "").split(":", 1)[0]
        quantity = self.exchange.amount_to_precision(resolved, preview["quantity"])

        endpoint = getattr(self.exchange, "fapiPrivatePostOrderTest", None)
        if endpoint is None:
            raise RuntimeError("installed CCXT build does not expose Binance Futures order/test endpoint")
        response = endpoint(
            {
                "symbol": raw_symbol,
                "side": side_value,
                "type": "MARKET",
                "quantity": quantity,
                "newClientOrderId": client_id,
            }
        )
        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "creates_order": False,
            "client_order_id": client_id,
            "preview": preview,
            "exchange_response": response,
        }

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        target_notional_usdt: float,
        client_order_id: str,
        confirm: str | None,
    ) -> dict:
        """Place a virtual-money MARKET order on Binance USD-M Demo/Testnet only."""
        self._require_credentials()
        self._confirm(confirm, "PLACE_TESTNET_ORDER")
        side_value = self._validate_side(side)
        client_id = self._validate_client_order_id(client_order_id)
        preview = self._preview(symbol, target_notional_usdt)
        resolved = preview["symbol"]
        order = self.exchange.create_order(
            resolved,
            "market",
            side_value.lower(),
            preview["quantity"],
            None,
            {"newClientOrderId": client_id},
        )
        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "virtual_money_only": True,
            "order": self._safe_order(order),
        }

    def fetch_order(self, *, symbol: str, order_id: str) -> dict:
        self._require_credentials()
        resolved = self.market.resolve_symbol(symbol)
        return self._safe_order(self.exchange.fetch_order(order_id, resolved))

    def cancel_order(self, *, symbol: str, order_id: str, confirm: str | None) -> dict:
        self._require_credentials()
        self._confirm(confirm, "CANCEL_TESTNET_ORDER")
        resolved = self.market.resolve_symbol(symbol)
        order = self.exchange.cancel_order(order_id, resolved)
        return {"ok": True, "environment": self.environment, "order": self._safe_order(order)}

    def close_position(
        self,
        *,
        symbol: str,
        confirm: str | None,
        client_order_id: str,
    ) -> dict:
        """Close one one-way-mode Demo/Testnet position with a reduce-only MARKET order."""
        self._require_credentials()
        self._confirm(confirm, "CLOSE_TESTNET_POSITION")
        client_id = self._validate_client_order_id(client_order_id)
        resolved = self.market.resolve_symbol(symbol)
        positions = self.exchange.fetch_positions([resolved])
        active = [p for p in positions or [] if abs(float(p.get("contracts") or 0.0)) > 0]
        if len(active) != 1:
            raise RuntimeError(f"expected exactly one active Testnet position for {resolved}, found {len(active)}")

        position = active[0]
        contracts = abs(float(position.get("contracts") or 0.0))
        position_side = str(position.get("side") or "").lower()
        if position_side not in {"long", "short"}:
            raise RuntimeError("cannot determine Testnet position side")
        close_side = "sell" if position_side == "long" else "buy"
        quantity = float(self.exchange.amount_to_precision(resolved, contracts))
        order = self.exchange.create_order(
            resolved,
            "market",
            close_side,
            quantity,
            None,
            {"reduceOnly": True, "newClientOrderId": client_id},
        )
        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "virtual_money_only": True,
            "reduce_only": True,
            "order": self._safe_order(order),
        }

    @staticmethod
    def _safe_order(order: dict | None) -> dict:
        order = order or {}
        return {
            "id": order.get("id"),
            "client_order_id": order.get("clientOrderId") or order.get("client_order_id"),
            "symbol": order.get("symbol"),
            "type": order.get("type"),
            "side": order.get("side"),
            "status": order.get("status"),
            "amount": order.get("amount"),
            "filled": order.get("filled"),
            "remaining": order.get("remaining"),
            "average": order.get("average"),
            "price": order.get("price"),
            "timestamp": order.get("timestamp"),
        }
