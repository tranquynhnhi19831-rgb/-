from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.database import Base
from models.position import Position
from models.trade import Trade
from services.runtime_supervisor import RuntimeSupervisor


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_runtime_starts_fail_closed_and_requires_explicit_kill_switch_release():
    db = _db()
    supervisor = RuntimeSupervisor()
    try:
        status = supervisor.status(db)
        assert status["kill_switch"] is True
        blocked = supervisor.acquire_lease(db, "worker-a")
        assert blocked.allowed is False
        assert blocked.code == "KILL_SWITCH_ENGAGED"

        supervisor.set_kill_switch(db, False)
        acquired = supervisor.acquire_lease(db, "worker-a", ttl_seconds=90)
        assert acquired.allowed is True
        assert acquired.code == "OK"

        other = supervisor.acquire_lease(db, "worker-b", ttl_seconds=90)
        assert other.allowed is False
        assert other.code == "LEASE_HELD"
    finally:
        db.close()


def test_ledger_mismatch_engages_kill_switch():
    db = _db()
    supervisor = RuntimeSupervisor()
    try:
        supervisor.set_kill_switch(db, False)
        db.add(
            Position(
                symbol="BTC/USDT",
                side="LONG",
                entry_price=100,
                mark_price=100,
                quantity=0.1,
                leverage=1,
                unrealized_pnl=0,
                is_open=True,
            )
        )
        db.commit()

        result = supervisor.validate_local_ledger(db)
        assert result.ok is False
        assert "OPEN_POSITION_TRADE_COUNT_MISMATCH" in result.errors
        assert supervisor.status(db)["kill_switch"] is True
    finally:
        db.close()


def test_matching_trade_and_position_pass_ledger_guard():
    db = _db()
    supervisor = RuntimeSupervisor()
    try:
        db.add(
            Trade(
                symbol="ETH/USDT",
                side="SHORT",
                entry_price=100,
                exit_price=0,
                stop_loss=102,
                take_profit=96.4,
                quantity=0.2,
                leverage=1,
                fee=0,
                pnl=0,
                dry_run=True,
                reason="test",
                deepseek_summary="",
                close_time=None,
            )
        )
        db.add(
            Position(
                symbol="ETH/USDT",
                side="SHORT",
                entry_price=100,
                mark_price=100,
                quantity=0.2,
                leverage=1,
                unrealized_pnl=0,
                is_open=True,
            )
        )
        db.commit()
        result = supervisor.validate_local_ledger(db)
        assert result.ok is True
        assert result.errors == ()
    finally:
        db.close()
