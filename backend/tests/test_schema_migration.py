from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from models.database import Base
from models import (  # noqa: F401
    account_snapshot,
    config_model,
    log,
    paper_order_intent,
    position,
    risk_event,
    runtime_state,
    signal,
    trade,
    trade_decision,
)
from services.schema_migration import run_schema_migrations, verify_required_schema


def test_migration_adds_runtime_checkpoint_to_legacy_table_and_scrubs_config():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE runtime_state (
                    id INTEGER PRIMARY KEY,
                    mode TEXT NOT NULL,
                    kill_switch BOOLEAN NOT NULL,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at DATETIME,
                    heartbeat_at DATETIME,
                    last_cycle_id TEXT NOT NULL,
                    last_error TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE config (
                    id INTEGER PRIMARY KEY,
                    binance_api_key TEXT,
                    binance_secret TEXT,
                    testnet BOOLEAN,
                    dry_run BOOLEAN,
                    live_confirmed BOOLEAN,
                    enabled_symbols TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO config VALUES (1, 'legacy-key', 'legacy-secret', 0, 0, 1, 'BTC/USDT')"
            )
        )

    applied = run_schema_migrations(engine)
    assert applied == [1, 2]
    assert "last_execution_close_at" in {
        col["name"] for col in inspect(engine).get_columns("runtime_state")
    }
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT binance_api_key, binance_secret, testnet, dry_run, live_confirmed, enabled_symbols FROM config"
            )
        ).one()
        assert row[0] == ""
        assert row[1] == ""
        assert row[2] == 1
        assert row[3] == 1
        assert row[4] == 0
        assert "BTC/USDT" in row[5]
        assert "HYPE/USDT" in row[5]

    # Idempotent: a second startup applies nothing.
    assert run_schema_migrations(engine) == []


def test_fresh_current_schema_passes_verification():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    run_schema_migrations(engine)
    verify_required_schema(engine)


def test_verifier_rejects_unknown_schema_drift():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE config (id INTEGER PRIMARY KEY)"))
        conn.execute(
            text(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
        )
    try:
        verify_required_schema(engine)
    except RuntimeError as exc:
        assert "DATABASE_SCHEMA_INVALID" in str(exc)
        assert "MISSING_COLUMNS:config" in str(exc)
    else:
        raise AssertionError("expected fail-closed schema verification")
