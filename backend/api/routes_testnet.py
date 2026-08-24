from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from config import INITIAL_TRADING_UNIVERSE, UNIVERSE_AS_OF_UTC
from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials, _proxy_config_from_env

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


def _required(payload: dict, key: str):
    if key not in payload or payload[key] is None or payload[key] == "":
        raise ValueError(f"explicit field required: {key}")
    return payload[key]


def _bad_request(exc: Exception):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status")
def testnet_status():
    creds = _credentials()
    return {
        "environment": "TESTNET",
        "credentials_configured": creds.configured,
        "proxy_configured": bool(_proxy_config_from_env()),
        "order_routes_enabled": _orders_enabled(),
        "mainnet_orders_supported": False,
        "credential_source": "SERVER_ENV_ONLY",
        "fixed_universe": list(INITIAL_TRADING_UNIVERSE),
        "universe_as_of_utc": UNIVERSE_AS_OF_UTC,
    }


@router.get("/health")
def testnet_authenticated_health():
    try:
        return _gateway().authenticated_health()
    except Exception as exc:
        _bad_request(exc)


@router.get("/universe-health")
def testnet_universe_health():
    """Read-only public-market preflight for the fixed seven-symbol universe."""
    try:
        result = _gateway().market.validate_usdm_universe(INITIAL_TRADING_UNIVERSE)
        return {
            "environment": "TESTNET",
            "binance_mode": "DEMO_TRADING",
            "universe_as_of_utc": UNIVERSE_AS_OF_UTC,
            **result,
        }
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
    """Signed Binance order validation; `/fapi/v1/order/test` creates no order.

    All order semantics must be explicit even though this endpoint creates no
    order. This prevents a future caller from accidentally inheriting default
    symbol/side/notional behavior.
    """
    try:
        return _gateway().test_market_order(
            symbol=str(_required(payload, "symbol")),
            side=str(_required(payload, "side")),
            target_notional_usdt=float(_required(payload, "target_notional_usdt")),
            client_order_id=str(_required(payload, "client_order_id")),
            confirm=str(_required(payload, "confirm")),
        )
    except Exception as exc:
        _bad_request(exc)


@router.post("/market-order")
def testnet_market_order(payload: dict):
    """Place a virtual-money Demo order only when the private runtime enables it."""
    _require_order_routes_enabled()
    try:
        return _gateway().place_market_order(
            symbol=str(_required(payload, "symbol")),
            side=str(_required(payload, "side")),
            target_notional_usdt=float(_required(payload, "target_notional_usdt")),
            client_order_id=str(_required(payload, "client_order_id")),
            confirm=str(_required(payload, "confirm")),
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
            symbol=str(_required(payload, "symbol")),
            order_id=str(_required(payload, "order_id")),
            confirm=str(_required(payload, "confirm")),
        )
    except Exception as exc:
        _bad_request(exc)


@router.post("/close-position")
def testnet_close_position(payload: dict):
    _require_order_routes_enabled()
    try:
        return _gateway().close_position(
            symbol=str(_required(payload, "symbol")),
            client_order_id=str(_required(payload, "client_order_id")),
            confirm=str(_required(payload, "confirm")),
        )
    except Exception as exc:
        _bad_request(exc)
