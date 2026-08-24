from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.database import Base
from models.trade import Trade
from services.account_service import realized_pnl_for_utc_day


def test_realized_pnl_query_does_not_autoflush_trade_being_closed():
    engine = create_engine("sqlite:///:memory:")
    # Deliberately use SQLAlchemy's default autoflush=True. Production currently
    # uses autoflush=False, but accounting semantics must not depend on that.
    db = sessionmaker(bind=engine, autoflush=True)()
    Base.metadata.create_all(bind=engine)
    try:
        trade = Trade(
            symbol="BTC/USDT",
            side="LONG",
            entry_price=100,
            exit_price=0,
            stop_loss=98,
            take_profit=103.6,
            quantity=0.1,
            leverage=1,
            fee=0,
            pnl=0,
            dry_run=True,
            reason="test",
            deepseek_summary="",
            close_time=None,
        )
        db.add(trade)
        db.commit()

        # Simulate the exact critical section in a Paper close: ORM state has
        # the new realized result, but we still need the pre-close daily sum.
        trade.pnl = -0.25
        trade.close_time = datetime.now(timezone.utc)

        assert realized_pnl_for_utc_day(db) == 0.0

        db.commit()
        assert realized_pnl_for_utc_day(db) == -0.25
    finally:
        db.close()
