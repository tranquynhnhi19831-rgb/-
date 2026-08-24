from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import ccxt

from exchange.binance_client import BinanceClient

TESTNET_ENVIRONMENT = "TESTNET"
BINANCE_USDM_DEMO_REST_BASE = "https://demo-fapi.binance.com"
# 100U * 10% max margin * 3x leverage = 30U maximum position notional.
MAX_TESTNET_ORDER_NOTIONAL_USDT = 30.0
HARD_TESTNET_MAX_LEVERAGE = 3
CLIENT_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


class AmbiguousDemoOrderState(RuntimeError):
    """Create request may have reached Binance, but its final state is unknown.

    Callers must reconcile by clientOrderId. They must never retry the create
    blindly because that can duplicate exposure after a transport timeout.
    """


def _proxy_config_from_env() -> dict[str, str]:
    """Build explicit CCXT requests proxies from standard environment variables."""

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
    """Private Binance USD-M Demo gateway with no Mainnet execution path.

    Order creation is idempotent by caller-supplied clientOrderId. A network
    failure during create is treated as an ambiguous exchange state: the gateway
    performs read-only reconciliation by origClientOrderId and never blindly
    submits the create request a second time.
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
        enable_demo = getattr(self.exchange, "enable_demo_trading", None)
        if enable_demo is None:
            raise RuntimeError(
                "installed CCXT does not support Binance Demo Trading; CCXT >= 4.5.6 is required"
            )
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
        actual_notional = float(preview["actual_notional_usdt"])
        if actual_notional > self.max_order_notional_usdt + 1e-9:
            raise ValueError(
                "Binance minimum quantity/notional would exceed the S7 hard position cap: "
                f"{actual_notional:.4f} > {self.max_order_notional_usdt:.2f} USDT"
            )
        return preview

    @staticmethod
    def _raw_symbol(exchange: Any, resolved: str) -> str:
        market = exchange.market(resolved)
        return str(market.get("id") or resolved.replace("/", "").split(":", 1)[0])

    @staticmethod
    def _order_not_found(exc: Exception) -> bool:
        if isinstance(exc, getattr(ccxt, "OrderNotFound", ())):
            return True
        text = str(exc).lower()
        return "-2013" in text or "order does not exist" in text or "unknown order" in text

    def fetch_order_by_client_id(self, *, symbol: str, client_order_id: str) -> dict | None:
        """Read-only lookup by Binance origClientOrderId."""
        self._require_credentials()
        client_id = self._validate_client_order_id(client_order_id)
        resolved = self.market.resolve_symbol(symbol)
        raw_symbol = self._raw_symbol(self.exchange, resolved)
        endpoint = getattr(self.exchange, "fapiPrivateGetOrder", None)
        if endpoint is None:
            raise RuntimeError("installed CCXT build does not expose Binance Futures GET order endpoint")
        try:
            raw = endpoint({"symbol": raw_symbol, "origClientOrderId": client_id})
        except Exception as exc:
            if self._order_not_found(exc):
                return None
            raise
        return self._safe_raw_order(raw)

    def _reconcile_client_order_after_ambiguous_create(
        self,
        *,
        symbol: str,
        client_order_id: str,
        attempts: int = 3,
    ) -> dict | None:
        # Read retries are safe; create retries are not.
        for attempt in range(max(1, attempts)):
            try:
                order = self.fetch_order_by_client_id(symbol=symbol, client_order_id=client_order_id)
                if order is not None:
                    return order
            except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout):
                pass
            if attempt + 1 < attempts:
                time.sleep(0.25 * (2**attempt))
        return None

    @staticmethod
    def _assert_existing_order_identity(existing: dict, *, client_id: str, side: str) -> None:
        existing_client = str(existing.get("client_order_id") or "")
        existing_side = str(existing.get("side") or "").upper()
        if existing_client and existing_client != client_id:
            raise RuntimeError("clientOrderId reconciliation returned a different client id")
        if existing_side and existing_side != side:
            raise RuntimeError("clientOrderId already belongs to an order with a different side")

    def execution_account_preflight(
        self,
        *,
        symbol: str,
        max_leverage: int = HARD_TESTNET_MAX_LEVERAGE,
    ) -> dict:
        """Read-only validation of account/symbol execution invariants.

        No account setting is changed. Actual Demo order creation is allowed only
        when the account is one-way, the symbol is isolated, and leverage is in
        [1, max_leverage]. Unknown settings fail closed.
        """
        self._require_credentials()
        if max_leverage < 1 or max_leverage > HARD_TESTNET_MAX_LEVERAGE:
            raise ValueError(f"max_leverage must be between 1 and {HARD_TESTNET_MAX_LEVERAGE}")

        position_mode_endpoint = getattr(self.exchange, "fapiPrivateGetPositionSideDual", None)
        if position_mode_endpoint is None:
            raise RuntimeError("cannot verify Binance Futures position mode")
        mode = position_mode_endpoint({}) or {}
        raw_dual = mode.get("dualSidePosition")
        if isinstance(raw_dual, str):
            dual_side = raw_dual.strip().lower() == "true"
        elif raw_dual is None:
            raise RuntimeError("Binance position mode response is missing dualSidePosition")
        else:
            dual_side = bool(raw_dual)
        if dual_side:
            raise RuntimeError("HEDGE_MODE_NOT_ALLOWED: system requires one-way position mode")

        resolved = self.market.resolve_symbol(symbol)
        positions = self.exchange.fetch_positions([resolved]) or []
        matching = [p for p in positions if str(p.get("symbol") or "") == resolved]
        if len(matching) != 1:
            raise RuntimeError(f"POSITION_CONFIG_UNAVAILABLE: expected one position config for {resolved}, found {len(matching)}")
        position = matching[0]
        info = position.get("info") if isinstance(position.get("info"), dict) else {}
        margin_mode = str(position.get("marginMode") or info.get("marginType") or "").lower()
        if not margin_mode and info.get("isolated") is not None:
            raw_isolated = info.get("isolated")
            isolated = raw_isolated if isinstance(raw_isolated, bool) else str(raw_isolated).lower() == "true"
            margin_mode = "isolated" if isolated else "cross"
        if margin_mode != "isolated":
            raise RuntimeError(f"MARGIN_MODE_NOT_ISOLATED: {resolved} margin mode is {margin_mode or 'unknown'}")

        raw_leverage = position.get("leverage") or info.get("leverage")
        try:
            leverage = int(float(raw_leverage))
        except (TypeError, ValueError):
            raise RuntimeError(f"LEVERAGE_UNAVAILABLE: cannot verify leverage for {resolved}")
        if leverage < 1 or leverage > max_leverage:
            raise RuntimeError(f"MAX_LEVERAGE_EXCEEDED: {resolved} leverage={leverage}, max={max_leverage}")

        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "symbol": resolved,
            "position_mode": "ONE_WAY",
            "margin_mode": "isolated",
            "leverage": leverage,
            "max_allowed_leverage": max_leverage,
            "mutated_settings": False,
        }

    def status(self) -> dict:
        return {
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "official_rest_base": BINANCE_USDM_DEMO_REST_BASE,
            "credentials_configured": self.credentials.configured,
            "demo_trading_required": True,
            "mainnet_orders_supported": False,
            "max_order_notional_usdt": self.max_order_notional_usdt,
            "max_leverage": HARD_TESTNET_MAX_LEVERAGE,
            "proxy_configured": bool(_proxy_config_from_env()),
            "idempotency": "CLIENT_ORDER_ID_RECONCILIATION_NO_BLIND_CREATE_RETRY",
        }

    def authenticated_health(self) -> dict:
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
                    "margin_mode": position.get("marginMode"),
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
        self._require_credentials()
        self._confirm(confirm, "TESTNET_ORDER_TEST")
        side_value = self._validate_side(side)
        client_id = self._validate_client_order_id(client_order_id)
        preview = self._preview(symbol, target_notional_usdt)
        resolved = preview["symbol"]
        raw_symbol = self._raw_symbol(self.exchange, resolved)
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
        """Place one idempotent virtual-money MARKET order on Binance Demo."""
        self._require_credentials()
        self._confirm(confirm, "PLACE_TESTNET_ORDER")
        side_value = self._validate_side(side)
        client_id = self._validate_client_order_id(client_order_id)
        preview = self._preview(symbol, target_notional_usdt)
        resolved = preview["symbol"]
        self.execution_account_preflight(symbol=resolved)

        existing = self.fetch_order_by_client_id(symbol=resolved, client_order_id=client_id)
        if existing is not None:
            self._assert_existing_order_identity(existing, client_id=client_id, side=side_value)
            return {
                "ok": True,
                "environment": self.environment,
                "binance_mode": "DEMO_TRADING",
                "virtual_money_only": True,
                "idempotent_replay": True,
                "recovered_after_ambiguous_create": False,
                "order": existing,
            }

        try:
            order = self.exchange.create_order(
                resolved,
                "market",
                side_value.lower(),
                preview["quantity"],
                None,
                {"newClientOrderId": client_id},
            )
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            recovered = self._reconcile_client_order_after_ambiguous_create(
                symbol=resolved,
                client_order_id=client_id,
            )
            if recovered is not None:
                self._assert_existing_order_identity(recovered, client_id=client_id, side=side_value)
                return {
                    "ok": True,
                    "environment": self.environment,
                    "binance_mode": "DEMO_TRADING",
                    "virtual_money_only": True,
                    "idempotent_replay": False,
                    "recovered_after_ambiguous_create": True,
                    "order": recovered,
                }
            raise AmbiguousDemoOrderState(
                f"AMBIGUOUS_ORDER_STATE client_order_id={client_id}; create was not retried; reconcile before any new order"
            ) from exc

        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "virtual_money_only": True,
            "idempotent_replay": False,
            "recovered_after_ambiguous_create": False,
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
        """Close one one-way Demo position with an idempotent reduce-only MARKET order."""
        self._require_credentials()
        self._confirm(confirm, "CLOSE_TESTNET_POSITION")
        client_id = self._validate_client_order_id(client_order_id)
        resolved = self.market.resolve_symbol(symbol)
        self.execution_account_preflight(symbol=resolved)

        existing = self.fetch_order_by_client_id(symbol=resolved, client_order_id=client_id)
        if existing is not None:
            return {
                "ok": True,
                "environment": self.environment,
                "binance_mode": "DEMO_TRADING",
                "virtual_money_only": True,
                "reduce_only": True,
                "idempotent_replay": True,
                "order": existing,
            }

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
        try:
            order = self.exchange.create_order(
                resolved,
                "market",
                close_side,
                quantity,
                None,
                {"reduceOnly": True, "newClientOrderId": client_id},
            )
        except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as exc:
            recovered = self._reconcile_client_order_after_ambiguous_create(
                symbol=resolved,
                client_order_id=client_id,
            )
            if recovered is not None:
                return {
                    "ok": True,
                    "environment": self.environment,
                    "binance_mode": "DEMO_TRADING",
                    "virtual_money_only": True,
                    "reduce_only": True,
                    "idempotent_replay": False,
                    "recovered_after_ambiguous_create": True,
                    "order": recovered,
                }
            raise AmbiguousDemoOrderState(
                f"AMBIGUOUS_CLOSE_STATE client_order_id={client_id}; close was not retried; reconcile before any new order"
            ) from exc
        return {
            "ok": True,
            "environment": self.environment,
            "binance_mode": "DEMO_TRADING",
            "virtual_money_only": True,
            "reduce_only": True,
            "idempotent_replay": False,
            "recovered_after_ambiguous_create": False,
            "order": self._safe_order(order),
        }

    @staticmethod
    def _safe_raw_order(order: dict | None) -> dict:
        order = order or {}
        return {
            "id": str(order.get("orderId") or order.get("id") or "") or None,
            "client_order_id": order.get("clientOrderId") or order.get("client_order_id"),
            "symbol": order.get("symbol"),
            "type": order.get("type"),
            "side": order.get("side"),
            "status": order.get("status"),
            "amount": float(order.get("origQty") or order.get("amount") or 0.0),
            "filled": float(order.get("executedQty") or order.get("filled") or 0.0),
            "remaining": None,
            "average": float(order.get("avgPrice") or order.get("average") or 0.0) or None,
            "price": float(order.get("price") or 0.0) or None,
            "timestamp": order.get("updateTime") or order.get("time") or order.get("timestamp"),
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
