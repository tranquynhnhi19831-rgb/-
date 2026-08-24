from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from config import INITIAL_TRADING_UNIVERSE, UNIVERSE_AS_OF_UTC
from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials, _proxy_config_from_env
from models.database import get_db
from services.trade_audit_service import add_trade_decision, new_cycle_id, new_decision_id

router = APIRouter(prefix="/api/testnet", tags=["testnet"])


def _credentials() -> TestnetCredentials:
    return TestnetCredentials.from_env()


def _gateway() -> BinanceTestnetGateway:
    return BinanceTestnetGateway(_credentials())


def _orders_enabled() -> bool:
    return os.getenv("ENABLE_BINANCE_TESTNET_ORDERS", "false").strip().lower() == "true"


def _required(payload: dict, key: str):
    if key not in payload or payload[key] is None or payload[key] == "":
        raise ValueError(f"explicit field required: {key}")
    return payload[key]


def _bad_request(exc: Exception):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


def _intent_fields(payload: dict) -> tuple[str, str, float | None, str]:
    symbol = str(payload.get("symbol") or "")
    side = str(payload.get("side") or "")
    notional = payload.get("target_notional_usdt")
    try:
        notional_value = None if notional in (None, "") else float(notional)
    except (TypeError, ValueError):
        notional_value = None
    client_order_id = str(payload.get("client_order_id") or "")
    return symbol, side, notional_value, client_order_id


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
def testnet_order_test(payload: dict, db: Session = Depends(get_db)):
    """Signed Binance order validation; `/fapi/v1/order/test` creates no order.

    The request is audited before the exchange call. Success and rejection are
    appended under the same ``decision_id`` so a future investigation can see
    exactly what was intended and whether Binance accepted the signed payload.
    """
    cycle_id = new_cycle_id("demo-order-test")
    decision_id = new_decision_id()
    symbol, side, notional, client_id = _intent_fields(payload)
    add_trade_decision(
        db,
        cycle_id=cycle_id,
        decision_id=decision_id,
        symbol=symbol or "UNKNOWN",
        setup="MANUAL_DEMO_ORDER_TEST",
        side=side,
        stage="ORDER_INTENT",
        outcome="TEST_REQUESTED",
        candidate=True,
        selected=True,
        planned_notional_usdt=notional,
        client_order_id=client_id,
        reason_codes=["BINANCE_FAPI_ORDER_TEST"],
        evidence={"creates_order": False, "environment": "TESTNET"},
    )

    try:
        result = _gateway().test_market_order(
            symbol=str(_required(payload, "symbol")),
            side=str(_required(payload, "side")),
            target_notional_usdt=float(_required(payload, "target_notional_usdt")),
            client_order_id=str(_required(payload, "client_order_id")),
            confirm=str(_required(payload, "confirm")),
        )
        preview = result.get("preview") or {}
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_ORDER_TEST",
            side=side,
            stage="ORDER_TEST",
            outcome="VALIDATED",
            candidate=True,
            selected=True,
            quantity=preview.get("quantity"),
            planned_notional_usdt=preview.get("actual_notional_usdt") or notional,
            client_order_id=client_id,
            reason_codes=["SIGNED_REQUEST_ACCEPTED", "NO_ORDER_CREATED"],
            evidence={"environment": "TESTNET", "creates_order": False, "preview": preview},
        )
        return {**result, "cycle_id": cycle_id, "decision_id": decision_id}
    except Exception as exc:
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol or "UNKNOWN",
            setup="MANUAL_DEMO_ORDER_TEST",
            side=side,
            stage="ORDER_TEST",
            outcome="REJECTED",
            candidate=True,
            selected=True,
            planned_notional_usdt=notional,
            client_order_id=client_id,
            reason_codes=["SIGNED_REQUEST_REJECTED"],
            evidence={"environment": "TESTNET", "creates_order": False, "error_type": type(exc).__name__},
            risk_code="ORDER_TEST_REJECTED",
            risk_message=str(exc),
        )
        _bad_request(exc)


@router.post("/market-order")
def testnet_market_order(payload: dict, db: Session = Depends(get_db)):
    """Place virtual-money Demo order only when private runtime enables it."""
    cycle_id = new_cycle_id("demo-order")
    decision_id = new_decision_id()
    symbol, side, notional, client_id = _intent_fields(payload)
    add_trade_decision(
        db,
        cycle_id=cycle_id,
        decision_id=decision_id,
        symbol=symbol or "UNKNOWN",
        setup="MANUAL_DEMO_MARKET_ORDER",
        side=side,
        stage="ORDER_INTENT",
        outcome="REQUESTED",
        candidate=True,
        selected=True,
        planned_notional_usdt=notional,
        client_order_id=client_id,
        reason_codes=["DEMO_MARKET_ORDER_REQUEST"],
        evidence={"environment": "TESTNET", "virtual_money_only": True},
    )

    if not _orders_enabled():
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol or "UNKNOWN",
            setup="MANUAL_DEMO_MARKET_ORDER",
            side=side,
            stage="EXECUTION_GATE",
            outcome="BLOCKED",
            candidate=True,
            selected=True,
            planned_notional_usdt=notional,
            client_order_id=client_id,
            reason_codes=["TESTNET_ORDER_ROUTES_DISABLED"],
            risk_code="TESTNET_ORDER_ROUTES_DISABLED",
            risk_message="ENABLE_BINANCE_TESTNET_ORDERS is false",
        )
        raise HTTPException(
            status_code=403,
            detail="Testnet order routes are disabled; set ENABLE_BINANCE_TESTNET_ORDERS=true on the private runtime",
        )

    try:
        result = _gateway().place_market_order(
            symbol=str(_required(payload, "symbol")),
            side=str(_required(payload, "side")),
            target_notional_usdt=float(_required(payload, "target_notional_usdt")),
            client_order_id=str(_required(payload, "client_order_id")),
            confirm=str(_required(payload, "confirm")),
        )
        order = result.get("order") or {}
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_MARKET_ORDER",
            side=side,
            stage="EXCHANGE_ORDER",
            outcome="ACCEPTED",
            candidate=True,
            selected=True,
            quantity=order.get("filled") or order.get("amount"),
            planned_notional_usdt=notional,
            client_order_id=client_id,
            exchange_order_id=str(order.get("id") or ""),
            reason_codes=["BINANCE_DEMO_ORDER_ACCEPTED"],
            evidence={"environment": "TESTNET", "virtual_money_only": True, "safe_order": order},
        )
        return {**result, "cycle_id": cycle_id, "decision_id": decision_id}
    except Exception as exc:
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol or "UNKNOWN",
            setup="MANUAL_DEMO_MARKET_ORDER",
            side=side,
            stage="EXCHANGE_ORDER",
            outcome="REJECTED",
            candidate=True,
            selected=True,
            planned_notional_usdt=notional,
            client_order_id=client_id,
            reason_codes=["BINANCE_DEMO_ORDER_REJECTED"],
            evidence={"environment": "TESTNET", "virtual_money_only": True, "error_type": type(exc).__name__},
            risk_code="EXCHANGE_ORDER_REJECTED",
            risk_message=str(exc),
        )
        _bad_request(exc)


@router.get("/order")
def testnet_get_order(symbol: str, order_id: str):
    try:
        return _gateway().fetch_order(symbol=symbol, order_id=order_id)
    except Exception as exc:
        _bad_request(exc)


@router.post("/cancel-order")
def testnet_cancel_order(payload: dict, db: Session = Depends(get_db)):
    cycle_id = new_cycle_id("demo-cancel")
    decision_id = new_decision_id()
    symbol = str(payload.get("symbol") or "UNKNOWN")
    order_id = str(payload.get("order_id") or "")
    add_trade_decision(
        db,
        cycle_id=cycle_id,
        decision_id=decision_id,
        symbol=symbol,
        setup="MANUAL_DEMO_CANCEL",
        stage="CANCEL_INTENT",
        outcome="REQUESTED",
        candidate=True,
        selected=True,
        exchange_order_id=order_id,
        reason_codes=["DEMO_CANCEL_REQUEST"],
    )
    if not _orders_enabled():
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_CANCEL",
            stage="EXECUTION_GATE",
            outcome="BLOCKED",
            candidate=True,
            selected=True,
            exchange_order_id=order_id,
            reason_codes=["TESTNET_ORDER_ROUTES_DISABLED"],
            risk_code="TESTNET_ORDER_ROUTES_DISABLED",
        )
        raise HTTPException(status_code=403, detail="Testnet order routes are disabled")
    try:
        result = _gateway().cancel_order(
            symbol=str(_required(payload, "symbol")),
            order_id=str(_required(payload, "order_id")),
            confirm=str(_required(payload, "confirm")),
        )
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_CANCEL",
            stage="CANCEL",
            outcome="ACCEPTED",
            candidate=True,
            selected=True,
            exchange_order_id=order_id,
            reason_codes=["BINANCE_DEMO_CANCEL_ACCEPTED"],
            evidence={"safe_order": result.get("order") or {}},
        )
        return {**result, "cycle_id": cycle_id, "decision_id": decision_id}
    except Exception as exc:
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_CANCEL",
            stage="CANCEL",
            outcome="REJECTED",
            candidate=True,
            selected=True,
            exchange_order_id=order_id,
            reason_codes=["BINANCE_DEMO_CANCEL_REJECTED"],
            risk_message=str(exc),
        )
        _bad_request(exc)


@router.post("/close-position")
def testnet_close_position(payload: dict, db: Session = Depends(get_db)):
    cycle_id = new_cycle_id("demo-close")
    decision_id = new_decision_id()
    symbol = str(payload.get("symbol") or "UNKNOWN")
    client_id = str(payload.get("client_order_id") or "")
    add_trade_decision(
        db,
        cycle_id=cycle_id,
        decision_id=decision_id,
        symbol=symbol,
        setup="MANUAL_DEMO_CLOSE_POSITION",
        stage="EXIT_INTENT",
        outcome="REQUESTED",
        candidate=True,
        selected=True,
        client_order_id=client_id,
        reason_codes=["DEMO_REDUCE_ONLY_CLOSE_REQUEST"],
    )
    if not _orders_enabled():
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_CLOSE_POSITION",
            stage="EXECUTION_GATE",
            outcome="BLOCKED",
            candidate=True,
            selected=True,
            client_order_id=client_id,
            reason_codes=["TESTNET_ORDER_ROUTES_DISABLED"],
            risk_code="TESTNET_ORDER_ROUTES_DISABLED",
        )
        raise HTTPException(status_code=403, detail="Testnet order routes are disabled")
    try:
        result = _gateway().close_position(
            symbol=str(_required(payload, "symbol")),
            client_order_id=str(_required(payload, "client_order_id")),
            confirm=str(_required(payload, "confirm")),
        )
        order = result.get("order") or {}
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_CLOSE_POSITION",
            side=str(order.get("side") or ""),
            stage="EXIT_ORDER",
            outcome="ACCEPTED",
            candidate=True,
            selected=True,
            quantity=order.get("filled") or order.get("amount"),
            client_order_id=client_id,
            exchange_order_id=str(order.get("id") or ""),
            reason_codes=["BINANCE_DEMO_REDUCE_ONLY_CLOSE_ACCEPTED"],
            evidence={"reduce_only": True, "safe_order": order},
        )
        return {**result, "cycle_id": cycle_id, "decision_id": decision_id}
    except Exception as exc:
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup="MANUAL_DEMO_CLOSE_POSITION",
            stage="EXIT_ORDER",
            outcome="REJECTED",
            candidate=True,
            selected=True,
            client_order_id=client_id,
            reason_codes=["BINANCE_DEMO_REDUCE_ONLY_CLOSE_REJECTED"],
            risk_message=str(exc),
        )
        _bad_request(exc)
