from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials

router = APIRouter(prefix="/api/testnet", tags=["testnet"])


def _credentials() -> TestnetCredentials:
    return TestnetCredentials.from_env()


def _gateway() -> BinanceTestnetGateway:
    return BinanceTestnetGateway(_credentials())


def _orders_enabled() -> bool:
    return os.getenv("ENABLE_BINANCE_TESTNET_ORDERS", "false").strip().lower() == "true"


def _require_order_routes_enabled() -> None:
    if not _orders_enabled():
        raise HTTPException(
            status_code=403,
            detail="Testnet order routes are disabled; set ENABLE_BINANCE_TESTNET_ORDERS=true on the private runtime",
        )


def _bad_request(exc: Exception):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
def testnet_status():
    creds = _credentials()
    return {
        "environment": "TESTNET",
        "credentials_configured": creds.configured,
        "order_routes_enabled": _orders_enabled(),
        "mainnet_orders_supported": False,
        "credential_source": "SERVER_ENV_ONLY",
    }


@router.get("/health")
def testnet_authenticated_health():
    try:
        return _gateway().authenticated_health()
    except Exception as exc:
        _bad_request(exc)


@router.get("/snapshot")
def testnet_snapshot():
    try:
        return _gateway().account_snapshot()
    except Exception as exc:
        _bad_request(exc)


@router.post("/order-test")
def testnet_order_test(payload: dict):
    """Signed Binance order validation; `/fapi/v1/order/test` creates no order."""
    try:
        return _gateway().test_market_order(
            symbol=str(payload.get("symbol", "BTC/USDT")),
            side=str(payload.get("side", "BUY")),
            target_notional_usdt=float(payload.get("target_notional_usdt", 5.0)),
            client_order_id=str(payload.get("client_order_id", "")),
            confirm=payload.get("confirm"),
        )
    except Exception as exc:
        _bad_request(exc)


@router.post("/market-order")
def testnet_market_order(payload: dict):
    """Place a virtual-money Testnet order only when the private runtime enables it."""
    _require_order_routes_enabled()
    try:
        return _gateway().place_market_order(
            symbol=str(payload.get("symbol", "BTC/USDT")),
            side=str(payload.get("side", "BUY")),
            target_notional_usdt=float(payload.get("target_notional_usdt", 5.0)),
            client_order_id=str(payload.get("client_order_id", "")),
            confirm=payload.get("confirm"),
        )
    except Exception as exc:
        _bad_request(exc)


@router.get("/order")
def testnet_get_order(symbol: str, order_id: str):
    try:
        return _gateway().fetch_order(symbol=symbol, order_id=order_id)
    except Exception as exc:
        _bad_request(exc)


@router.post("/cancel-order")
def testnet_cancel_order(payload: dict):
    _require_order_routes_enabled()
    try:
        return _gateway().cancel_order(
            symbol=str(payload.get("symbol", "BTC/USDT")),
            order_id=str(payload.get("order_id", "")),
            confirm=payload.get("confirm"),
        )
    except Exception as exc:
        _bad_request(exc)


@router.post("/close-position")
def testnet_close_position(payload: dict):
    _require_order_routes_enabled()
    try:
        return _gateway().close_position(
            symbol=str(payload.get("symbol", "BTC/USDT")),
            client_order_id=str(payload.get("client_order_id", "")),
            confirm=payload.get("confirm"),
        )
    except Exception as exc:
        _bad_request(exc)
