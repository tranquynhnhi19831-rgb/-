from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes_config import _ensure_config, save_config
from models.config_model import ConfigModel
from models.database import Base


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_s7_config_purges_legacy_binance_secrets_and_live_flags():
    db = _db()
    try:
        cfg = ConfigModel(
            binance_api_key="legacy-key",
            binance_secret="legacy-secret",
            testnet=False,
            dry_run=False,
            live_confirmed=True,
            enabled_symbols="BTC/USDT",
        )
        db.add(cfg)
        db.commit()

        loaded = _ensure_config(db)

        assert loaded.binance_api_key == ""
        assert loaded.binance_secret == ""
        assert loaded.testnet is True
        assert loaded.dry_run is True
        assert loaded.live_confirmed is False
    finally:
        db.close()


def test_config_post_cannot_persist_binance_credentials_or_unlock_s7_mode():
    db = _db()
    try:
        result = save_config(
            {
                "binance_api_key": "should-not-persist",
                "binance_secret": "should-not-persist",
                "testnet": False,
                "dry_run": False,
                "live_confirmed": True,
                "enabled_symbols": ["BTC/USDT"],
            },
            db,
        )
        cfg = db.query(ConfigModel).first()

        assert result["ok"] is True
        assert result["s7_mode_locked"] is True
        assert cfg.binance_api_key == ""
        assert cfg.binance_secret == ""
        assert cfg.testnet is True
        assert cfg.dry_run is True
        assert cfg.live_confirmed is False
    finally:
        db.close()
