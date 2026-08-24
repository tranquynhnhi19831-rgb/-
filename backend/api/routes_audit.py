from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models.database import get_db
from models.trade_decision import TradeDecision
from services.trade_audit_service import decode_json_field

router = APIRouter(prefix="/api/audit", tags=["audit"])


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
    return {
        "count": len(rows),
        "items": [
            {
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
            for row in rows
        ],
    }
