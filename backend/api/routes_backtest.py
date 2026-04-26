from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from services.backtest_service import run_backtest
from models.database import get_db
from models.config_model import ConfigModel

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run")
def backtest(payload: dict, db: Session = Depends(get_db)):
    cfg = db.query(ConfigModel).first()
    symbol = payload.get("symbol", "BTC/USDT")
    start = payload.get("start", "2025-01-01")
    end = payload.get("end", "2025-12-31")
    return run_backtest(symbol, start, end, cfg.testnet if cfg else True, cfg.binance_api_key if cfg else "", cfg.binance_secret if cfg else "")
