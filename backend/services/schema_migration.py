from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import inspect, text

from config import INITIAL_TRADING_UNIVERSE

MIGRATION_TABLE = "schema_migrations"


@dataclass(frozen=True)
class Migration:
    version: int
    name: str


MIGRATIONS = (
    Migration(1, "runtime_state_closed_candle_checkpoint"),
    Migration(2, "enforce_s7_safe_config_data"),
)

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "config": {
        "id",
        "binance_api_key",
        "binance_secret",
        "testnet",
        "dry_run",
        "live_confirmed",
        "enabled_symbols",
    },
    "trade_decisions": {
        "id",
        "decision_id",
        "cycle_id",
        "symbol",
        "stage",
        "outcome",
        "reason_codes_json",
        "evidence_json",
    },
    "runtime_state": {
        "id",
        "mode",
        "kill_switch",
        "lease_owner",
        "lease_expires_at",
        "heartbeat_at",
        "last_cycle_id",
        "last_execution_close_at",
        "last_error",
    },
    "paper_order_intents": {
        "id",
        "decision_id",
        "cycle_id",
        "symbol",
        "signal_close_time",
        "stop_reference",
        "status",
    },
}


def _ensure_migration_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
    )


def _applied_versions(conn) -> set[int]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {int(row[0]) for row in rows}


def _table_columns(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    if table not in inspector.get_table_names():
        return set()
    return {str(col["name"]) for col in inspector.get_columns(table)}


def _apply_v1(conn) -> None:
    columns = _table_columns(conn, "runtime_state")
    if columns and "last_execution_close_at" not in columns:
        conn.execute(text("ALTER TABLE runtime_state ADD COLUMN last_execution_close_at DATETIME"))


def _apply_v2(conn) -> None:
    # Credentials must never survive in the legacy SQLite config. Private Demo
    # credentials are SERVER_ENV_ONLY. S7 runtime also remains dry-run/testnet
    # locked, and the initial universe is fixed for reproducible research.
    if "config" not in inspect(conn).get_table_names():
        return
    conn.execute(
        text(
            """
            UPDATE config
            SET binance_api_key = '',
                binance_secret = '',
                testnet = 1,
                dry_run = 1,
                live_confirmed = 0,
                enabled_symbols = :symbols
            """
        ),
        {"symbols": ",".join(INITIAL_TRADING_UNIVERSE)},
    )


def run_schema_migrations(engine) -> list[int]:
    """Apply known additive/data migrations transactionally.

    Unknown schema drift is not guessed here. ``verify_required_schema`` runs
    afterwards and fails startup if the resulting database still cannot satisfy
    the current runtime contract.
    """

    applied_now: list[int] = []
    with engine.begin() as conn:
        _ensure_migration_table(conn)
        applied = _applied_versions(conn)
        for migration in MIGRATIONS:
            if migration.version in applied:
                continue
            if migration.version == 1:
                _apply_v1(conn)
            elif migration.version == 2:
                _apply_v2(conn)
            else:
                raise RuntimeError(f"unknown schema migration: {migration.version}")
            conn.execute(
                text(
                    "INSERT INTO schema_migrations(version, name, applied_at) "
                    "VALUES (:version, :name, :applied_at)"
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            applied_now.append(migration.version)
    return applied_now


def verify_required_schema(engine) -> None:
    """Fail closed if runtime-critical tables/columns are missing."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    errors: list[str] = []
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables:
            errors.append(f"MISSING_TABLE:{table}")
            continue
        actual = {str(col["name"]) for col in inspector.get_columns(table)}
        missing = sorted(required.difference(actual))
        if missing:
            errors.append(f"MISSING_COLUMNS:{table}:{','.join(missing)}")

    if MIGRATION_TABLE not in tables:
        errors.append(f"MISSING_TABLE:{MIGRATION_TABLE}")

    if errors:
        raise RuntimeError("DATABASE_SCHEMA_INVALID:" + ";".join(errors))
