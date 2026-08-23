from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from config import REFERENCE_CAPITAL_USDT
from models.database import get_db
from models.position import Position
from models.trade import Trade
from services.account_service import latest_account

router = APIRouter(prefix="/api/public", tags=["public-read-only"])


def _position(row: Position) -> dict:
    notional = abs(float(row.quantity or 0) * float(row.mark_price or 0))
    return {
        "id": row.id,
        "symbol": row.symbol,
        "side": row.side,
        "entry_price": row.entry_price,
        "mark_price": row.mark_price,
        "quantity": row.quantity,
        "notional_usdt": notional,
        "leverage": row.leverage,
        "unrealized_pnl": row.unrealized_pnl,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _trade(row: Trade) -> dict:
    return {
        "id": row.id,
        "symbol": row.symbol,
        "side": row.side,
        "open_time": row.open_time.isoformat() if row.open_time else None,
        "close_time": row.close_time.isoformat() if row.close_time else None,
        "entry_price": row.entry_price,
        "exit_price": row.exit_price,
        "quantity": row.quantity,
        "leverage": row.leverage,
        "fee": row.fee,
        "pnl": row.pnl,
        "dry_run": row.dry_run,
        "strategy_reason": row.reason,
    }


@router.get("/health")
def public_health():
    return {"ok": True, "mode": "READ_ONLY"}


@router.get("/snapshot")
def public_snapshot(db: Session = Depends(get_db)):
    account = latest_account(db)
    positions = (
        db.query(Position)
        .filter(Position.is_open.is_(True))
        .order_by(desc(Position.updated_at))
        .limit(20)
        .all()
    )
    trades = db.query(Trade).order_by(desc(Trade.id)).limit(30).all()

    equity = float(account.get("equity") or account.get("balance") or 0.0)
    total_return_pct = (
        ((equity / REFERENCE_CAPITAL_USDT) - 1.0) * 100.0
        if REFERENCE_CAPITAL_USDT > 0
        else 0.0
    )

    closed = [row for row in trades if row.close_time is not None]
    wins = sum(1 for row in closed if float(row.pnl or 0) > 0)
    losses = sum(1 for row in closed if float(row.pnl or 0) < 0)

    return {
        "read_only": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            **account,
            "initial_capital_usdt": REFERENCE_CAPITAL_USDT,
            "total_return_pct": total_return_pct,
        },
        "positions": [_position(row) for row in positions],
        "recent_trades": [_trade(row) for row in trades],
        "statistics": {
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": (wins / len(closed) * 100.0) if closed else 0.0,
        },
        "capabilities": {
            "can_read": True,
            "can_start_engine": False,
            "can_stop_engine": False,
            "can_change_config": False,
            "can_place_order": False,
        },
    }
