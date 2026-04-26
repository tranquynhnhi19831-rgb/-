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


@router.get("/api/status")
def status():
    return {"running": ENGINE.running}


@router.post("/api/start")
async def start(db: Session = Depends(get_db)):
    ENGINE.running = True
    await ENGINE.start_once(db)
    return {"ok": True, "running": True}


@router.post("/api/stop")
def stop():
    ENGINE.running = False
    return {"ok": True, "running": False}


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
