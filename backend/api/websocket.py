import asyncio
from fastapi import APIRouter, WebSocket
from models.database import SessionLocal
from services.trading_engine import ENGINE

router = APIRouter()


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            db = SessionLocal()
            payload = ENGINE.snapshot(db)
            db.close()
            await ws.send_json(payload)
            await asyncio.sleep(2)
    except Exception:
        await ws.close()
