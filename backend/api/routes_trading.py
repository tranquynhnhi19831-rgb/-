from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session
from models.database import get_db
from models.trade import Trade
from models.position import Position
from models.signal import Signal
from models.risk_event import RiskEvent
from models.log import Log
from services.trading_engine import ENGINE

router = APIRouter(tags=["trading"])

EXECUTION_MODEL = "MANUAL_SINGLE_CYCLE"


@router.get("/api/status")
def status():
    return {
        "running": ENGINE.running,
        "execution_model": EXECUTION_MODEL,
        "mode": "LOCAL_PAPER",
        "source": "DETERMINISTIC_PAPER_SCENARIO",
        "binance_orders": False,
    }


@router.post("/api/start")
async def start(db: Session = Depends(get_db)):
    """Execute exactly one deterministic Local Paper cycle.

    This is not a background worker. `running` is true only while the cycle is
    executing and returns to false on success or error. A future scheduler can
    introduce a persistent RUNNING state without misrepresenting the current
    S7.2 behavior.
    """

    if ENGINE.running:
        return {
            "ok": False,
            "running": True,
            "execution_model": EXECUTION_MODEL,
            "mode": "LOCAL_PAPER",
            "binance_orders": False,
            "error": "PAPER_CYCLE_ALREADY_RUNNING",
        }

    ENGINE.running = True
    try:
        cycle = await ENGINE.start_once(db)
        return {
            "ok": True,
            "running": False,
            "cycle_complete": True,
            "execution_model": EXECUTION_MODEL,
            "mode": "LOCAL_PAPER",
            "binance_orders": False,
            "cycle": cycle,
        }
    finally:
        ENGINE.running = False


@router.post("/api/stop")
def stop():
    # Kept for compatibility with older UI/API clients. There is no persistent
    # Local Paper worker in S7.2, so this only clears the transient cycle flag.
    ENGINE.running = False
    return {
        "ok": True,
        "running": False,
        "execution_model": EXECUTION_MODEL,
        "mode": "LOCAL_PAPER",
    }


@router.get("/api/positions")
def positions(db: Session = Depends(get_db)):
    rows = db.query(Position).order_by(desc(Position.id)).limit(50).all()
    return [r.__dict__ | {"_sa_instance_state": None} for r in rows]


@router.get("/api/trades")
def trades(db: Session = Depends(get_db)):
    rows = db.query(Trade).order_by(desc(Trade.id)).limit(100).all()
    return [r.__dict__ | {"_sa_instance_state": None} for r in rows]


@router.get("/api/signals")
def signals(db: Session = Depends(get_db)):
    rows = db.query(Signal).order_by(desc(Signal.id)).limit(100).all()
    return [r.__dict__ | {"_sa_instance_state": None} for r in rows]


@router.get("/api/logs")
def logs(db: Session = Depends(get_db)):
    rows = db.query(Log).order_by(desc(Log.id)).limit(200).all()
    return [r.__dict__ | {"_sa_instance_state": None} for r in rows]


@router.get("/api/risk-events")
def risk_events(db: Session = Depends(get_db)):
    rows = db.query(RiskEvent).order_by(desc(RiskEvent.id)).limit(100).all()
    return [r.__dict__ | {"_sa_instance_state": None} for r in rows]
