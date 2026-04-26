import asyncio
from fastapi import APIRouter, WebSocket
from models.database import SessionLocal
from services.account_service import latest_account

router = APIRouter()


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            db = SessionLocal()
            account = latest_account(db)
            db.close()
            await ws.send_json({"type": "account", "payload": account})
            await asyncio.sleep(2)
    except Exception:
        await ws.close()
