from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session
from models.database import get_db, SessionLocal
from models.trade import Trade
from models.position import Position
from models.signal import Signal
from models.risk_event import RiskEvent
from models.log import Log
from services.trading_engine import ENGINE

router = APIRouter(tags=["trading"])


@router.get("/api/status")
def status(db: Session = Depends(get_db)):
    snap = ENGINE.snapshot(db)
    account = snap.get("account", {})
    mode = "dry-run" if account.get("source") == "simulation" else ("testnet" if "testnet" in account.get("source", "") else "live")
    return {"running": ENGINE.running, "mode": mode, "last_market_update": ENGINE.last_market_update}


@router.post("/api/start")
async def start():
    ok, msg = await ENGINE.start(SessionLocal)
    return {"ok": ok, "message": msg, "running": ENGINE.running}


@router.post("/api/stop")
async def stop():
    ok, msg = await ENGINE.stop()
    return {"ok": ok, "message": msg, "running": ENGINE.running}


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
