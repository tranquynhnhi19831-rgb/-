from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from config import (
    ALLOWED_SYMBOLS,
    DEFAULT_CONFIG,
    HARD_MAX_DAILY_LOSS,
    HARD_MAX_LEVERAGE,
    HARD_MAX_RISK_PER_TRADE,
    REFERENCE_CAPITAL_USDT,
)
from exchange.binance_client import BinanceClient
from models.config_model import ConfigModel
from models.database import get_db
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


def _secret_value(payload: dict, key: str, current: str) -> str:
    value = payload.get(key)
    if value is None:
        return current
    text = str(value)
    # Never persist the masked value returned by GET /api/config.
    if "*" in text:
        return current
    return text


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
        "default_leverage": min(cfg.default_leverage, HARD_MAX_LEVERAGE),
        "max_leverage": min(cfg.max_leverage, HARD_MAX_LEVERAGE),
        "risk_per_trade": min(cfg.risk_per_trade, HARD_MAX_RISK_PER_TRADE),
        "max_margin_per_trade": cfg.max_margin_per_trade,
        "max_daily_loss": min(cfg.max_daily_loss, HARD_MAX_DAILY_LOSS),
        "max_trades_per_day": cfg.max_trades_per_day,
        "max_open_positions": cfg.max_open_positions,
        "max_consecutive_losses": cfg.max_consecutive_losses,
        "enabled_symbols": [s for s in cfg.enabled_symbols.split(",") if s],
        "allowed_symbols": ALLOWED_SYMBOLS,
        "reference_capital_usdt": REFERENCE_CAPITAL_USDT,
        "execution_status": "S1_PUBLIC_DATA_AND_PREVIEW_ONLY",
    }


@router.post("")
def save_config(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    enabled_symbols = [s for s in payload.get("enabled_symbols", []) if s in ALLOWED_SYMBOLS]

    max_leverage = max(
        1,
        min(int(payload.get("max_leverage", cfg.max_leverage)), HARD_MAX_LEVERAGE),
    )
    default_leverage = max(
        1,
        min(int(payload.get("default_leverage", cfg.default_leverage)), max_leverage),
    )

    updates = {
        "binance_api_key": _secret_value(payload, "binance_api_key", cfg.binance_api_key),
        "binance_secret": _secret_value(payload, "binance_secret", cfg.binance_secret),
        "deepseek_api_key": _secret_value(payload, "deepseek_api_key", cfg.deepseek_api_key),
        "testnet": bool(payload.get("testnet", True)),
        "dry_run": bool(payload.get("dry_run", True)),
        "live_confirmed": bool(payload.get("live_confirmed", False)),
        "margin_mode": "isolated",
        "default_leverage": default_leverage,
        "max_leverage": max_leverage,
        "risk_per_trade": max(
            0.0001,
            min(float(payload.get("risk_per_trade", cfg.risk_per_trade)), HARD_MAX_RISK_PER_TRADE),
        ),
        "max_margin_per_trade": max(
            0.01,
            min(float(payload.get("max_margin_per_trade", cfg.max_margin_per_trade)), 0.10),
        ),
        "max_daily_loss": max(
            0.005,
            min(float(payload.get("max_daily_loss", cfg.max_daily_loss)), HARD_MAX_DAILY_LOSS),
        ),
        "max_trades_per_day": max(1, min(int(payload.get("max_trades_per_day", 3)), 5)),
        "max_open_positions": 1,
        "max_consecutive_losses": 3,
        "enabled_symbols": ",".join(enabled_symbols or ["BTC/USDT"]),
    }

    # S1 does not contain a live Binance order path. Keep the explicit guard in
    # place so a future execution adapter cannot be enabled accidentally.
    if not updates["testnet"] and not updates["dry_run"] and not updates["live_confirmed"]:
        return {"ok": False, "error": "进入live模式前必须二次确认"}

    for key, value in updates.items():
        setattr(cfg, key, value)
    db.commit()
    return {"ok": True}


@router.post("/test-binance")
def test_binance(payload: dict, db: Session = Depends(get_db)):
    cfg = _ensure_config(db)
    client = BinanceClient(
        payload.get("api_key", cfg.binance_api_key),
        payload.get("secret", cfg.binance_secret),
        payload.get("testnet", cfg.testnet),
    )
    return client.test_connection()


@router.post("/binance-order-preview")
def binance_order_preview(payload: dict, db: Session = Depends(get_db)):
    """Preview a Binance-valid quantity; this endpoint never places an order."""
    cfg = _ensure_config(db)
    client = BinanceClient(cfg.binance_api_key, cfg.binance_secret, cfg.testnet)
    symbol = payload.get("symbol", "BTC/USDT")
    if symbol not in ALLOWED_SYMBOLS:
        return {"ok": False, "error": "币种未启用或不在白名单"}

    try:
        preview = client.preview_market_order(
            symbol=symbol,
            target_notional_usdt=float(payload.get("target_notional_usdt", 10.0)),
            price=float(payload["price"]) if payload.get("price") is not None else None,
        )
        return {"ok": True, **preview}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/test-deepseek")
async def test_deepseek(payload: dict):
    svc = DeepSeekService()
    return await svc.test_connection(payload.get("api_key", ""))
