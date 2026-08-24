from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from config import INITIAL_TRADING_UNIVERSE
from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials
from models.database import get_db
from services.exchange_reconciliation import reconcile_local_with_demo

router = APIRouter(prefix="/api/testnet", tags=["testnet-safety"])


def _gateway() -> BinanceTestnetGateway:
    return BinanceTestnetGateway(TestnetCredentials.from_env())


def _bad_request(exc: Exception):
    raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/execution-preflight")
def execution_preflight(symbol: str = Query(..., min_length=1)):
    """Read-only account/symbol invariant check; never changes Binance settings."""
    if symbol not in INITIAL_TRADING_UNIVERSE:
        raise HTTPException(status_code=400, detail="symbol outside fixed seven-symbol universe")
    try:
        return _gateway().execution_account_preflight(symbol=symbol)
    except Exception as exc:
        _bad_request(exc)


@router.get("/order-by-client-id")
def order_by_client_id(
    symbol: str = Query(..., min_length=1),
    client_order_id: str = Query(..., min_length=1),
):
    """Read-only recovery lookup for an ambiguous create/close state."""
    if symbol not in INITIAL_TRADING_UNIVERSE:
        raise HTTPException(status_code=400, detail="symbol outside fixed seven-symbol universe")
    try:
        order = _gateway().fetch_order_by_client_id(symbol=symbol, client_order_id=client_order_id)
        return {
            "ok": True,
            "environment": "TESTNET",
            "binance_mode": "DEMO_TRADING",
            "found": order is not None,
            "order": order,
        }
    except Exception as exc:
        _bad_request(exc)


@router.get("/reconciliation")
def reconciliation(db: Session = Depends(get_db)):
    """Read-only local-ledger versus Binance Demo reconciliation.

    No state is repaired automatically. Any mismatch is returned explicitly and
    must block future autonomous exchange execution until investigated.
    """
    try:
        snapshot = _gateway().account_snapshot()
        result = reconcile_local_with_demo(db, snapshot)
        return {
            "environment": "TESTNET",
            "binance_mode": "DEMO_TRADING",
            **result.to_dict(),
        }
    except Exception as exc:
        _bad_request(exc)
