from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db
from models.config_model import ConfigModel
from config import DEFAULT_CONFIG, ALLOWED_SYMBOLS
from exchange.binance_client import BinanceClient
from services.deepseek_service import DeepSeekService

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
        "has_binance_api_key": bool(cfg.binance_api_key),
        "has_binance_secret": bool(cfg.binance_secret),
        "has_deepseek_api_key": bool(cfg.deepseek_api_key),
        "deepseek_base_url": cfg.deepseek_base_url,
        "deepseek_model": cfg.deepseek_model,
        "testnet": cfg.testnet,
        "dry_run": cfg.dry_run,
        "live_confirmed": cfg.live_confirmed,
        "margin_mode": cfg.margin_mode,
        "default_leverage": min(cfg.default_leverage, 5),
        "max_leverage": 5,
        "risk_per_trade": min(cfg.risk_per_trade, 0.01),
        "max_margin_per_trade": min(cfg.max_margin_per_trade, 0.10),
        "max_daily_loss": min(cfg.max_daily_loss, 0.03),
        "max_trades_per_day": min(cfg.max_trades_per_day, 3),
        "max_open_positions": 1,
        "max_consecutive_losses": 3,
        "cooldown_seconds": cfg.cooldown_seconds,
        "loop_interval_seconds": cfg.loop_interval_seconds,
        "enabled_symbols": [s for s in cfg.enabled_symbols.split(",") if s],
        "allowed_symbols": ALLOWED_SYMBOLS,
    }


@router.post("")
def save_config(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    enabled_symbols = [s for s in payload.get("enabled_symbols", []) if s in ALLOWED_SYMBOLS]

    if payload.get("binance_api_key"):
        cfg.binance_api_key = payload["binance_api_key"].strip()
    if payload.get("binance_secret"):
        cfg.binance_secret = payload["binance_secret"].strip()
    if payload.get("deepseek_api_key"):
        cfg.deepseek_api_key = payload["deepseek_api_key"].strip()

    cfg.deepseek_base_url = payload.get("deepseek_base_url", cfg.deepseek_base_url)
    cfg.deepseek_model = payload.get("deepseek_model", cfg.deepseek_model)
    cfg.testnet = payload.get("testnet", True)
    cfg.dry_run = payload.get("dry_run", True)
    cfg.live_confirmed = bool(payload.get("live_confirmed", False))
    cfg.margin_mode = "isolated"
    cfg.default_leverage = min(int(payload.get("default_leverage", 1)), 5)
    cfg.max_leverage = 5
    cfg.risk_per_trade = min(float(payload.get("risk_per_trade", 0.01)), 0.01)
    cfg.max_margin_per_trade = min(float(payload.get("max_margin_per_trade", 0.10)), 0.10)
    cfg.max_daily_loss = min(float(payload.get("max_daily_loss", 0.03)), 0.03)
    cfg.max_trades_per_day = min(int(payload.get("max_trades_per_day", 3)), 3)
    cfg.max_open_positions = 1
    cfg.max_consecutive_losses = 3
    cfg.cooldown_seconds = max(int(payload.get("cooldown_seconds", cfg.cooldown_seconds)), 60)
    cfg.loop_interval_seconds = max(int(payload.get("loop_interval_seconds", cfg.loop_interval_seconds)), 30)
    cfg.enabled_symbols = ",".join(enabled_symbols or ["BTC/USDT"])

    if not cfg.testnet and not cfg.dry_run and not cfg.live_confirmed:
        return {"ok": False, "error": "进入live模式前必须二次确认"}

    db.commit()
    return {"ok": True}


@router.post("/test-binance")
def test_binance(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    api_key = payload.get("api_key") or cfg.binance_api_key
    secret = payload.get("secret") or cfg.binance_secret
    client = BinanceClient(api_key, secret, payload.get("testnet", cfg.testnet))
    return client.test_connection()


@router.post("/test-deepseek")
async def test_deepseek(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    svc = DeepSeekService()
    return await svc.test_connection(
        payload.get("api_key") or cfg.deepseek_api_key,
        payload.get("base_url") or cfg.deepseek_base_url,
        payload.get("model") or cfg.deepseek_model,
    )
