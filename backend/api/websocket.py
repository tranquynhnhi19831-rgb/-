import asyncio
from fastapi import APIRouter, WebSocket

from models.database import SessionLocal
from services.account_service import latest_account, realized_pnl_for_utc_day

router = APIRouter()


@router.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            db = SessionLocal()
            try:
                account = latest_account(db)
                account["daily_pnl"] = realized_pnl_for_utc_day(db)
            finally:
                db.close()
            await ws.send_json({"type": "account", "payload": account})
            await asyncio.sleep(2)
    except Exception:
        await ws.close()
