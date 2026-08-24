import asyncio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.database import Base
from models.trade_decision import TradeDecision
from services.trading_engine import TradingEngine


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_paper_open_and_close_share_auditable_decision_lifecycle():
    db = _db()
    engine = TradingEngine()
    try:
        opened = asyncio.run(engine.start_once(db))
        assert opened["action"] == "OPEN_PAPER_POSITION"
        decision_id = opened["decision_id"]

        rows = (
            db.query(TradeDecision)
            .filter(TradeDecision.decision_id == decision_id)
            .order_by(TradeDecision.id)
            .all()
        )
        assert [row.stage for row in rows] == ["CANDIDATE", "ORDER_INTENT", "FILL"]
        assert rows[-1].trade_id is not None

        closed = asyncio.run(engine.start_once(db))
        assert closed["action"] == "CLOSE_PAPER_POSITION"
        assert closed["decision_id"] == decision_id

        rows = (
            db.query(TradeDecision)
            .filter(TradeDecision.decision_id == decision_id)
            .order_by(TradeDecision.id)
            .all()
        )
        assert [row.stage for row in rows] == ["CANDIDATE", "ORDER_INTENT", "FILL", "EXIT"]
        assert rows[-1].outcome == "CLOSED"
    finally:
        db.close()
