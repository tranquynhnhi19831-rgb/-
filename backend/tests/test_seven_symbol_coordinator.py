import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config import INITIAL_TRADING_UNIVERSE
from models.database import Base
from models.trade_decision import TradeDecision
from services.seven_symbol_coordinator import SevenSymbolScanCoordinator
from services.universe_scanner import CandidateIntent


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_scan_once_evaluates_all_seven_and_selects_best_candidate():
    db = _db()
    seen = []

    async def evaluator(symbol):
        seen.append(symbol)
        if symbol == "ETH/USDT":
            return CandidateIntent(symbol, "PULLBACK", "LONG", 0.80, 100.0, 98.0)
        if symbol == "SOL/USDT":
            return CandidateIntent(symbol, "BREAKOUT", "LONG", 0.85, 50.0, 49.0)
        return None

    try:
        result = asyncio.run(SevenSymbolScanCoordinator().scan_once(db, evaluator))

        assert tuple(seen) == INITIAL_TRADING_UNIVERSE
        assert result.scanned_symbols == INITIAL_TRADING_UNIVERSE
        assert result.candidate_count == 2
        assert result.selected is not None
        assert result.selected.intent.symbol == "SOL/USDT"

        rows = db.query(TradeDecision).all()
        assert len(rows) == 4
        assert len([r for r in rows if r.stage == "CANDIDATE"]) == 2
        assert len([r for r in rows if r.stage == "ARBITRATION" and r.selected]) == 1
    finally:
        db.close()


def test_scan_once_with_no_candidate_still_scans_entire_universe_without_fake_trade():
    db = _db()
    seen = []

    def evaluator(symbol):
        seen.append(symbol)
        return None

    try:
        result = asyncio.run(SevenSymbolScanCoordinator().scan_once(db, evaluator))

        assert tuple(seen) == INITIAL_TRADING_UNIVERSE
        assert result.candidate_count == 0
        assert result.selected is None
        assert db.query(TradeDecision).count() == 0
    finally:
        db.close()
