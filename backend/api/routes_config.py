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
from exchange.testnet_gateway import BinanceTestnetGateway, TestnetCredentials
from models.config_model import ConfigModel
from models.database import get_db
from services.deepseek_service import DeepSeekService
from utils.security import mask_secret

router = APIRouter(prefix="/api/config", tags=["config"])


def _purge_legacy_binance_secrets(cfg: ConfigModel, db: Session) -> None:
    """Remove legacy DB-persisted Binance credentials.

    S7 private Binance Demo credentials are SERVER_ENV_ONLY. Keeping a second
    credential copy in SQLite creates ambiguity and unnecessary secret-at-rest
    exposure, so any historical values are erased when config is accessed.
    """

    if cfg.binance_api_key or cfg.binance_secret:
        cfg.binance_api_key = ""
        cfg.binance_secret = ""
        db.commit()


def _enforce_s7_mode(cfg: ConfigModel, db: Session) -> None:
    """Fail closed on all legacy Live-mode flags while the system is in S7."""

    changed = False
    if cfg.testnet is not True:
        cfg.testnet = True
        changed = True
    if cfg.dry_run is not True:
        cfg.dry_run = True
        changed = True
    if cfg.live_confirmed:
        cfg.live_confirmed = False
        changed = True
    if changed:
        db.commit()


def _ensure_config(db: Session) -> ConfigModel:
    cfg = db.query(ConfigModel).first()
    if cfg:
        _purge_legacy_binance_secrets(cfg, db)
        _enforce_s7_mode(cfg, db)
        return cfg
    d = DEFAULT_CONFIG.model_dump()
    cfg = ConfigModel(**{**d, "enabled_symbols": ",".join(d["enabled_symbols"])})
    cfg.binance_api_key = ""
    cfg.binance_secret = ""
    cfg.testnet = True
    cfg.dry_run = True
    cfg.live_confirmed = False
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
        # Binance credentials intentionally never come from this config model.
        "binance_api_key": "",
        "binance_secret": "",
        "binance_credentials_source": "SERVER_ENV_ONLY",
        "deepseek_api_key": mask_secret(cfg.deepseek_api_key),
        "testnet": True,
        "dry_run": True,
        "live_confirmed": False,
        "s7_mode_locked": True,
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
        "execution_status": "S7_LOCAL_PAPER_AND_BINANCE_DEMO_VALIDATION",
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
        # S7 security locks: browser/admin config cannot enable Mainnet semantics.
        "binance_api_key": "",
        "binance_secret": "",
        "testnet": True,
        "dry_run": True,
        "live_confirmed": False,
        "deepseek_api_key": _secret_value(payload, "deepseek_api_key", cfg.deepseek_api_key),
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

    for key, value in updates.items():
        setattr(cfg, key, value)
    db.commit()
    return {
        "ok": True,
        "binance_credentials_source": "SERVER_ENV_ONLY",
        "s7_mode_locked": True,
    }


@router.post("/test-binance")
def test_binance(payload: dict, db: Session = Depends(get_db)):
    """Compatibility route: use the env-only Binance Demo private health check."""
    _ensure_config(db)
    try:
        result = BinanceTestnetGateway(TestnetCredentials.from_env()).authenticated_health()
        return {"deprecated_route": True, **result}
    except Exception as exc:
        return {"ok": False, "deprecated_route": True, "error": str(exc)}


@router.post("/binance-order-preview")
def binance_order_preview(payload: dict, db: Session = Depends(get_db)):
    """Preview a Demo-valid quantity; this endpoint never places an order."""
    _ensure_config(db)
    symbol = payload.get("symbol", "ETH/USDT")
    if symbol not in ALLOWED_SYMBOLS:
        return {"ok": False, "error": "币种未启用或不在白名单"}

    try:
        gateway = BinanceTestnetGateway(TestnetCredentials.from_env())
        preview = gateway._preview(
            symbol=symbol,
            target_notional_usdt=float(payload.get("target_notional_usdt", 10.0)),
        )
        return {"ok": True, **preview}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/test-deepseek")
async def test_deepseek(payload: dict):
    svc = DeepSeekService()
    return await svc.test_connection(payload.get("api_key", ""))
