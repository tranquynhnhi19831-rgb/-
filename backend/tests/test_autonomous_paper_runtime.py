from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.database import Base
from models.paper_order_intent import PaperOrderIntent
from models.position import Position
from models.trade import Trade
from services.autonomous_paper_runtime import AutonomousPaperRuntime
from services.runtime_supervisor import RuntimeSupervisor
from services.seven_symbol_coordinator import SevenSymbolScanCoordinator
from services.universe_scanner import CandidateIntent


def _bar(open_time: str, open_: float, high: float, low: float, close: float):
    opened = pd.Timestamp(open_time, tz="UTC")
    return {
        "open_time": opened,
        "timestamp": opened + pd.Timedelta(minutes=1),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1.0,
    }


class FakeProvider:
    def __init__(self, fill_bar):
        self.step = 0
        self.signal_bar = _bar("2026-01-01 00:00:00", 100, 101, 99, 100)
        self.fill_bar = fill_bar

    @property
    def current_close(self):
        return self.signal_bar["timestamp"] if self.step == 0 else self.fill_bar["timestamp"]

    def fetch_closed_ohlcv(self, symbol, timeframe, *, limit):
        assert timeframe == "1m"
        rows = [self.signal_bar] if self.step == 0 else [self.signal_bar, self.fill_bar]
        return pd.DataFrame(rows)


class FakeEvaluator:
    profile_name = "TEST_PROFILE"

    def __init__(self, provider, *, stop=98.0):
        self.provider = provider
        self.stop = stop

    def evaluate_symbol(self, symbol):
        if symbol != "ETH/USDT":
            return None
        return CandidateIntent(
            symbol=symbol,
            setup="TREND_PULLBACK_CONTINUATION",
            side="LONG",
            score=0.8,
            entry_reference=100.0,
            stop_reference=self.stop,
            target_reference=103.6,
            reason_codes=("TEST_SIGNAL",),
            evidence={"latest_closed_1m": str(self.provider.current_close)},
        )


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _runtime(db, provider, *, stop=98.0):
    supervisor = RuntimeSupervisor()
    supervisor.set_kill_switch(db, False)
    lease = supervisor.acquire_lease(db, "test-worker", ttl_seconds=90)
    assert lease.allowed
    return AutonomousPaperRuntime(
        provider=provider,
        evaluator=FakeEvaluator(provider, stop=stop),
        coordinator=SevenSymbolScanCoordinator(),
        supervisor=supervisor,
    )


def test_signal_is_persisted_then_filled_only_on_next_bar_open():
    db = _db()
    provider = FakeProvider(_bar("2026-01-01 00:01:00", 100, 101, 99, 100.5))
    runtime = _runtime(db, provider)
    try:
        first = asyncio.run(runtime.cycle_once(db, owner="test-worker"))
        assert first["action"] == "PENDING_NEXT_BAR"
        assert db.query(PaperOrderIntent).filter(PaperOrderIntent.status == "PENDING").count() == 1
        assert db.query(Trade).count() == 0

        provider.step = 1
        second = asyncio.run(runtime.cycle_once(db, owner="test-worker"))
        assert second["action"] == "FILL_PAPER_POSITION"
        trade = db.query(Trade).one()
        assert trade.entry_price > 100.0  # adverse entry slippage
        assert trade.close_time is None
        assert db.query(Position).filter(Position.is_open.is_(True)).count() == 1
        assert db.query(PaperOrderIntent).filter(PaperOrderIntent.status == "FILLED").count() == 1
    finally:
        db.close()


def test_next_bar_gap_through_stop_cancels_instead_of_chasing_entry():
    db = _db()
    provider = FakeProvider(_bar("2026-01-01 00:01:00", 97.0, 98.0, 96.0, 97.5))
    runtime = _runtime(db, provider, stop=98.0)
    try:
        asyncio.run(runtime.cycle_once(db, owner="test-worker"))
        provider.step = 1
        result = asyncio.run(runtime.cycle_once(db, owner="test-worker"))
        assert result["action"] == "PENDING_CANCELLED"
        assert result["reason_code"] == "ENTRY_GAPPED_THROUGH_STOP"
        assert db.query(Trade).count() == 0
        assert db.query(Position).count() == 0
    finally:
        db.close()


def test_same_bar_stop_and_target_uses_conservative_stop_first():
    db = _db()
    provider = FakeProvider(_bar("2026-01-01 00:01:00", 100.0, 104.0, 97.0, 101.0))
    runtime = _runtime(db, provider, stop=98.0)
    try:
        asyncio.run(runtime.cycle_once(db, owner="test-worker"))
        provider.step = 1
        result = asyncio.run(runtime.cycle_once(db, owner="test-worker"))
        assert result["action"] == "FILL_AND_EXIT"
        trade = db.query(Trade).one()
        assert trade.close_time is not None
        assert trade.pnl < 0
        assert db.query(Position).filter(Position.is_open.is_(True)).count() == 0
    finally:
        db.close()
