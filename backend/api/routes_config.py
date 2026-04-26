from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db
from models.config_model import ConfigModel
from config import DEFAULT_CONFIG, ALLOWED_SYMBOLS
from exchange.binance_client import BinanceClient
from services.deepseek_service import DeepSeekService
from utils.security import mask_secret

router = APIRouter(prefix="/api/config", tags=["config"])


def _ensure_config(db: Session) -> ConfigModel:
    cfg = db.query(ConfigModel).first()
    if cfg:
        return cfg
    d = DEFAULT_CONFIG.model_dump()
    cfg = ConfigModel(**{**d, "enabled_symbols": ",".join(d["enabled_symbols"])})
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


@router.get("")
def get_config(db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    return {
        "binance_api_key": mask_secret(cfg.binance_api_key),
        "binance_secret": mask_secret(cfg.binance_secret),
        "deepseek_api_key": mask_secret(cfg.deepseek_api_key),
        "testnet": cfg.testnet,
        "dry_run": cfg.dry_run,
        "live_confirmed": cfg.live_confirmed,
        "margin_mode": cfg.margin_mode,
        "default_leverage": min(cfg.default_leverage, 5),
        "max_leverage": 5,
        "risk_per_trade": min(cfg.risk_per_trade, 0.01),
        "max_margin_per_trade": cfg.max_margin_per_trade,
        "max_daily_loss": cfg.max_daily_loss,
        "max_trades_per_day": cfg.max_trades_per_day,
        "max_open_positions": cfg.max_open_positions,
        "max_consecutive_losses": cfg.max_consecutive_losses,
        "enabled_symbols": [s for s in cfg.enabled_symbols.split(",") if s],
        "allowed_symbols": ALLOWED_SYMBOLS,
    }


@router.post("")
def save_config(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    enabled_symbols = [s for s in payload.get("enabled_symbols", []) if s in ALLOWED_SYMBOLS]
    updates = {
        "binance_api_key": payload.get("binance_api_key", cfg.binance_api_key),
        "binance_secret": payload.get("binance_secret", cfg.binance_secret),
        "deepseek_api_key": payload.get("deepseek_api_key", cfg.deepseek_api_key),
        "testnet": payload.get("testnet", True),
        "dry_run": payload.get("dry_run", True),
        "live_confirmed": bool(payload.get("live_confirmed", False)),
        "margin_mode": "isolated",
        "default_leverage": min(int(payload.get("default_leverage", 1)), 5),
        "max_leverage": 5,
        "risk_per_trade": min(float(payload.get("risk_per_trade", 0.01)), 0.01),
        "max_margin_per_trade": min(float(payload.get("max_margin_per_trade", 0.10)), 0.10),
        "max_daily_loss": min(float(payload.get("max_daily_loss", 0.03)), 0.03),
        "max_trades_per_day": min(int(payload.get("max_trades_per_day", 3)), 3),
        "max_open_positions": 1,
        "max_consecutive_losses": 3,
        "enabled_symbols": ",".join(enabled_symbols or ["BTC/USDT"]),
    }
    if not updates["testnet"] and not updates["dry_run"] and not updates["live_confirmed"]:
        return {"ok": False, "error": "进入live模式前必须二次确认"}

    for key, value in updates.items():
        setattr(cfg, key, value)
    db.commit()
    return {"ok": True}


@router.post("/test-binance")
def test_binance(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    client = BinanceClient(payload.get("api_key", cfg.binance_api_key), payload.get("secret", cfg.binance_secret), payload.get("testnet", cfg.testnet))
    return client.test_connection()


@router.post("/test-deepseek")
async def test_deepseek(payload: dict):
    svc = DeepSeekService()
    return await svc.test_connection(payload.get("api_key", ""))
