from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import ccxt

from exchange.binance_client import BinanceClient

TESTNET_ENVIRONMENT = "TESTNET"
MAX_TESTNET_ORDER_NOTIONAL_USDT = 10.0
CLIENT_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


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
    """Private Binance USD-M gateway that is structurally incapable of Mainnet trading.

    S7 deliberately has no Mainnet base-url switch. The gateway always enables
    CCXT sandbox mode before any market/private call. Real-money execution must
    be introduced later through a separately reviewed adapter.
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
            exchange = ccxt.binanceusdm(
                {
                    "apiKey": credentials.api_key,
                    "secret": credentials.secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"},
                }
            )
        self.exchange = exchange
        # Must happen before any exchange call. This is the primary S7 safety boundary.
        self.exchange.set_sandbox_mode(True)
        self.market = BinanceClient(exchange=self.exchange)

    @classmethod
    def from_env(cls) -> "BinanceTestnetGateway":
        return cls(TestnetCredentials.from_env())

    def _require_credentials(self) -> None:
        if not self.credentials.configured:
            raise RuntimeError(
                "Binance Testnet credentials are not configured; set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_SECRET"
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
                f"S7 Testnet order notional exceeds hard cap of {self.max_order_notional_usdt:.2f} USDT"
            )
        return self.market.preview_market_order(symbol, target_notional_usdt)

    def status(self) -> dict:
        """Local status only; does not make a network call."""
        return {
            "environment": self.environment,
            "credentials_configured": self.credentials.configured,
            "sandbox_required": True,
            "mainnet_orders_supported": False,
            "max_order_notional_usdt": self.max_order_notional_usdt,
        }

    def authenticated_health(self) -> dict:
        """Verify Testnet credentials with a read-only private account request."""
        self._require_credentials()
        balance = self.exchange.fetch_balance()
        usdt = balance.get("USDT", {}) if isinstance(balance, dict) else {}
        return {
            "ok": True,
            "environment": self.environment,
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
        """Place a virtual-money MARKET order on USD-M Futures Testnet only."""
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
        """Close one one-way-mode Testnet position with a reduce-only MARKET order."""
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
