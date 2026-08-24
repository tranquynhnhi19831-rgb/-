from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from models.database import get_db
from models.trade_decision import TradeDecision
from services.trade_audit_service import decode_json_field

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _serialize(row: TradeDecision) -> dict:
    return {
        "id": row.id,
        "decision_id": row.decision_id,
        "cycle_id": row.cycle_id,
        "symbol": row.symbol,
        "setup": row.setup,
        "side": row.side,
        "stage": row.stage,
        "outcome": row.outcome,
        "candidate": bool(row.candidate),
        "selected": bool(row.selected),
        "score": row.score,
        "entry_reference": row.entry_reference,
        "stop_reference": row.stop_reference,
        "target_reference": row.target_reference,
        "quantity": row.quantity,
        "planned_risk_usdt": row.planned_risk_usdt,
        "planned_notional_usdt": row.planned_notional_usdt,
        "reason_codes": decode_json_field(row.reason_codes_json, []),
        "evidence": decode_json_field(row.evidence_json, {}),
        "risk_code": row.risk_code,
        "risk_message": row.risk_message,
        "client_order_id": row.client_order_id,
        "exchange_order_id": row.exchange_order_id,
        "trade_id": row.trade_id,
        "created_at": row.created_at,
    }


@router.get("/trade-decisions")
def list_trade_decisions(
    symbol: str | None = None,
    decision_id: str | None = None,
    stage: str | None = None,
    outcome: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = db.query(TradeDecision)
    if symbol:
        query = query.filter(TradeDecision.symbol == symbol)
    if decision_id:
        query = query.filter(TradeDecision.decision_id == decision_id)
    if stage:
        query = query.filter(TradeDecision.stage == stage)
    if outcome:
        query = query.filter(TradeDecision.outcome == outcome)

    rows = query.order_by(desc(TradeDecision.id)).limit(limit).all()
    return {"count": len(rows), "items": [_serialize(row) for row in rows]}


@router.get("/decision/{decision_id}")
def decision_timeline(decision_id: str, db: Session = Depends(get_db)):
    """Return one strategy decision's append-only forensic lifecycle."""

    rows = (
        db.query(TradeDecision)
        .filter(TradeDecision.decision_id == decision_id)
        .order_by(asc(TradeDecision.id))
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="decision_id not found")

    symbols = {row.symbol for row in rows}
    sides = {row.side for row in rows if row.side}
    trade_ids = {row.trade_id for row in rows if row.trade_id is not None}
    stages = [row.stage for row in rows]
    outcomes = [row.outcome for row in rows]
    integrity_errors = []
    if len(symbols) != 1:
        integrity_errors.append("DECISION_SYMBOL_CHANGED")
    if len(sides) > 1:
        integrity_errors.append("DECISION_SIDE_CHANGED")
    if len(trade_ids) > 1:
        integrity_errors.append("DECISION_LINKS_MULTIPLE_TRADES")
    if "FILL" in stages and not trade_ids:
        integrity_errors.append("FILL_WITHOUT_TRADE_ID")

    terminal = any(
        stage == "EXIT" or outcome in {"BLOCKED", "CANCELLED", "CANCELLED_STALE_SIGNAL", "NOT_SELECTED"}
        for stage, outcome in zip(stages, outcomes)
    )
    return {
        "decision_id": decision_id,
        "symbol": next(iter(symbols)) if len(symbols) == 1 else None,
        "events": [_serialize(row) for row in rows],
        "event_count": len(rows),
        "latest_stage": rows[-1].stage,
        "latest_outcome": rows[-1].outcome,
        "trade_id": next(iter(trade_ids)) if len(trade_ids) == 1 else None,
        "terminal": terminal,
        "integrity_ok": not integrity_errors,
        "integrity_errors": integrity_errors,
    }
