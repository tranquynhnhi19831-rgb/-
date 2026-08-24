from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models.config_model import ConfigModel
from models.database import get_db
from services.runtime_supervisor import SUPERVISOR

router = APIRouter(tags=["runtime"])


class KillSwitchRequest(BaseModel):
    enabled: bool
    confirm: str
    reason: str = ""


def _orders_enabled() -> bool:
    return os.getenv("ENABLE_BINANCE_TESTNET_ORDERS", "").strip().lower() in {"1", "true", "yes", "on"}


@router.get("/api/runtime/status")
def runtime_status(db: Session = Depends(get_db)):
    ledger = SUPERVISOR.validate_local_ledger(db)
    return {
        **SUPERVISOR.status(db),
        "execution_scope": "AUTONOMOUS_PAPER_ONLY",
        "binance_order_routes_enabled": _orders_enabled(),
        "ledger": ledger.to_dict(),
    }


@router.post("/api/runtime/kill-switch")
def runtime_kill_switch(payload: KillSwitchRequest, db: Session = Depends(get_db)):
    if payload.enabled:
        if payload.confirm != "ENGAGE_PAPER_KILL_SWITCH":
            raise HTTPException(status_code=400, detail="explicit confirmation required: ENGAGE_PAPER_KILL_SWITCH")
        return SUPERVISOR.set_kill_switch(db, True, reason=payload.reason or "operator request")

    if payload.confirm != "ENABLE_AUTONOMOUS_PAPER":
        raise HTTPException(status_code=400, detail="explicit confirmation required: ENABLE_AUTONOMOUS_PAPER")
    if _orders_enabled():
        raise HTTPException(
            status_code=409,
            detail="autonomous Paper cannot be enabled while Binance Demo order routes are enabled",
        )

    cfg = db.query(ConfigModel).first()
    if cfg is not None and not bool(cfg.dry_run):
        raise HTTPException(status_code=409, detail="autonomous Paper requires dry_run=true")
    ledger = SUPERVISOR.validate_local_ledger(db)
    if not ledger.ok:
        raise HTTPException(status_code=409, detail={"code": "LOCAL_LEDGER_INVALID", "errors": list(ledger.errors)})

    return SUPERVISOR.set_kill_switch(db, False, reason=payload.reason or "operator enabled Paper runtime")
