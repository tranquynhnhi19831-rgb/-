from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from config import INITIAL_TRADING_UNIVERSE
from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials
from models.database import get_db
from models.trade_decision import TradeDecision
from services.exchange_reconciliation import reconcile_local_with_demo
from services.market_data_service import BinanceDemoClosedCandleProvider
from services.runtime_supervisor import SUPERVISOR
from services.strategy_runtime import BASELINE_PROFILE

router = APIRouter(prefix="/api/readiness", tags=["readiness"])

# The current runtime strategy is deliberately not promoted. Change this only
# after a frozen profile survives development windows + untouched validation +
# shared-equity portfolio replay. Runtime infrastructure must not infer strategy
# readiness from code availability alone.
STRATEGY_PROMOTED = False


def _orders_enabled() -> bool:
    return os.getenv("ENABLE_BINANCE_TESTNET_ORDERS", "").strip().lower() in {"1", "true", "yes", "on"}


def _order_test_accepted(db: Session) -> bool:
    return (
        db.query(TradeDecision)
        .filter(TradeDecision.stage == "ORDER_TEST", TradeDecision.outcome == "VALIDATED")
        .first()
        is not None
    )


def _probe_demo(db: Session) -> dict:
    result = {
        "public_universe": {"status": "NOT_CHECKED"},
        "private_health": {"status": "NOT_CHECKED"},
        "reconciliation": {"status": "NOT_CHECKED"},
    }
    try:
        public = BinanceDemoClosedCandleProvider().require_universe_health()
        result["public_universe"] = {"status": "PASS", "details": public}
    except Exception as exc:
        result["public_universe"] = {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}

    credentials = TestnetCredentials.from_env()
    if not credentials.configured:
        result["private_health"] = {"status": "BLOCKED", "reason": "DEMO_CREDENTIALS_NOT_CONFIGURED"}
        result["reconciliation"] = {"status": "BLOCKED", "reason": "DEMO_CREDENTIALS_NOT_CONFIGURED"}
        return result

    try:
        gateway = BinanceTestnetGateway(credentials)
        health = gateway.authenticated_health()
        result["private_health"] = {"status": "PASS", "details": health}
        snapshot = gateway.account_snapshot()
        reconciled = reconcile_local_with_demo(db, snapshot)
        result["reconciliation"] = {
            "status": "PASS" if reconciled.ok else "FAIL",
            "details": reconciled.to_dict(),
        }
    except Exception as exc:
        if result["private_health"]["status"] == "NOT_CHECKED":
            result["private_health"] = {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}
        result["reconciliation"] = {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}
    return result


@router.get("")
def readiness(
    probe_demo: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    runtime = SUPERVISOR.status(db)
    local_ledger = SUPERVISOR.validate_local_ledger(db)
    credentials = TestnetCredentials.from_env()
    order_test_passed = _order_test_accepted(db)
    demo_probe = _probe_demo(db) if probe_demo else {
        "public_universe": {"status": "NOT_CHECKED"},
        "private_health": {"status": "NOT_CHECKED"},
        "reconciliation": {"status": "NOT_CHECKED"},
    }

    static_gates = {
        "fixed_seven_symbol_universe": len(INITIAL_TRADING_UNIVERSE) == 7,
        "local_ledger_valid": bool(local_ledger.ok),
        "mainnet_supported": False,
        "demo_order_routes_enabled": _orders_enabled(),
        "demo_credentials_configured": credentials.configured,
        "order_test_accepted_in_audit": order_test_passed,
        "strategy_promoted": STRATEGY_PROMOTED,
    }
    probe_pass = (
        demo_probe["public_universe"]["status"] == "PASS"
        and demo_probe["private_health"]["status"] == "PASS"
        and demo_probe["reconciliation"]["status"] == "PASS"
    )

    engineering_ready_for_local_acceptance = bool(
        static_gates["fixed_seven_symbol_universe"]
        and static_gates["local_ledger_valid"]
        and not static_gates["mainnet_supported"]
        and not static_gates["demo_order_routes_enabled"]
    )
    ready_to_enable_demo_orders = bool(
        engineering_ready_for_local_acceptance
        and STRATEGY_PROMOTED
        and credentials.configured
        and order_test_passed
        and probe_demo
        and probe_pass
        and runtime.get("kill_switch", True)
    )

    return {
        "phase": "S7_PRE_DEMO_AUTONOMY",
        "strategy_profile": BASELINE_PROFILE,
        "strategy_promoted": STRATEGY_PROMOTED,
        "fixed_universe": list(INITIAL_TRADING_UNIVERSE),
        "runtime": runtime,
        "local_ledger": local_ledger.to_dict(),
        "gates": static_gates,
        "demo_probe_requested": probe_demo,
        "demo_probe": demo_probe,
        "engineering_ready_for_local_acceptance": engineering_ready_for_local_acceptance,
        "ready_to_enable_demo_orders": ready_to_enable_demo_orders,
        "blocking_reasons": [
            reason
            for condition, reason in (
                (not STRATEGY_PROMOTED, "STRATEGY_NOT_PROMOTED"),
                (not credentials.configured, "DEMO_CREDENTIALS_NOT_CONFIGURED"),
                (not order_test_passed, "SIGNED_ORDER_TEST_NOT_ACCEPTED"),
                (_orders_enabled(), "DEMO_ORDER_ROUTES_ALREADY_ENABLED_BEFORE_READINESS"),
                (not local_ledger.ok, "LOCAL_LEDGER_INVALID"),
                (probe_demo and not probe_pass, "DEMO_PROBE_NOT_FULLY_PASSING"),
                (not probe_demo, "DEMO_PROBE_NOT_RUN"),
            )
            if condition
        ],
    }
