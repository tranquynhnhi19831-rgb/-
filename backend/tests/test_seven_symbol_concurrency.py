from __future__ import annotations

import asyncio
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import INITIAL_TRADING_UNIVERSE
from models.database import Base
from services.seven_symbol_coordinator import SevenSymbolScanCoordinator


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_sync_evaluator_is_run_concurrently_across_full_universe():
    barrier = threading.Barrier(len(INITIAL_TRADING_UNIVERSE))
    seen = []
    lock = threading.Lock()

    def evaluator(symbol):
        with lock:
            seen.append(symbol)
        barrier.wait(timeout=3)
        return None

    db = _db()
    try:
        result = asyncio.run(SevenSymbolScanCoordinator().scan_once(db, evaluator))
        assert set(seen) == set(INITIAL_TRADING_UNIVERSE)
        assert result.scanned_symbols == INITIAL_TRADING_UNIVERSE
        assert result.candidate_count == 0
        assert result.selected is None
    finally:
        db.close()
