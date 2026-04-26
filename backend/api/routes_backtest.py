from fastapi import APIRouter
from services.backtest_service import run_backtest

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run")
def backtest(payload: dict):
    symbol = payload.get("symbol", "BTC/USDT")
    return run_backtest(symbol, payload.get("start", "2025-01-01"), payload.get("end", "2025-12-31"))
