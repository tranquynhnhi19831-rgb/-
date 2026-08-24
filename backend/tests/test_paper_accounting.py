from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.database import Base
from models.trade import Trade
from services.account_service import (
    consecutive_losses_for_utc_day,
    max_drawdown_from_equities,
    realized_pnl_for_utc_day,
    trades_opened_on_utc_day,
)
from services.trading_engine import TradingEngine


def test_drawdown_uses_equity_peak_not_initial_capital():
    peak = 100.23082764550514
    current = 100.09557747043738

    drawdown = TradingEngine._drawdown_fraction(peak, current)

    assert drawdown == pytest.approx(0.00134938699245424)
    assert drawdown * 100 == pytest.approx(0.134938699245424)


def test_historical_drawdown_reconstructs_existing_paper_history():
    equities = [100.0, 100.23082764550514, 100.09557747043738]

    drawdown = max_drawdown_from_equities(equities)

    assert drawdown == pytest.approx(0.00134938699245424)


def test_historical_drawdown_preserves_worst_prior_peak_to_trough():
    equities = [100.0, 101.0, 99.0, 102.0, 101.5]

    drawdown = max_drawdown_from_equities(equities)

    assert drawdown == pytest.approx((101.0 - 99.0) / 101.0)


def test_drawdown_is_zero_at_new_equity_high():
    assert TradingEngine._drawdown_fraction(100.0, 100.25) == 0.0


def test_drawdown_handles_nonpositive_peak_defensively():
    assert TradingEngine._drawdown_fraction(0.0, 99.0) == 0.0


def test_daily_pnl_and_trade_count_reset_by_utc_day():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        db.add_all(
            [
                Trade(
                    symbol="BTC/USDT",
                    side="LONG",
                    open_time=datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 23, 11, 0, tzinfo=timezone.utc),
                    pnl=-1.25,
                ),
                Trade(
                    symbol="BTC/USDT",
                    side="LONG",
                    open_time=datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc),
                    pnl=0.50,
                ),
                Trade(
                    symbol="BTC/USDT",
                    side="SHORT",
                    open_time=datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc),
                    close_time=None,
                    pnl=0.0,
                ),
            ]
        )
        db.commit()

        assert realized_pnl_for_utc_day(db, date(2026, 8, 23)) == pytest.approx(-1.25)
        assert realized_pnl_for_utc_day(db, date(2026, 8, 24)) == pytest.approx(0.50)
        assert trades_opened_on_utc_day(db, date(2026, 8, 23)) == 1
        assert trades_opened_on_utc_day(db, date(2026, 8, 24)) == 2
    finally:
        db.close()


def test_consecutive_losses_are_scoped_to_realization_utc_day():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        db.add_all(
            [
                # Previous-day loss must never leak into the next UTC day.
                Trade(
                    symbol="BTC/USDT",
                    side="LONG",
                    open_time=datetime(2026, 8, 23, 20, 0, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 23, 21, 0, tzinfo=timezone.utc),
                    pnl=-0.5,
                ),
                # Opened before midnight but realized after midnight: belongs to
                # Aug 24 because cooldown is based on realized result time.
                Trade(
                    symbol="BTC/USDT",
                    side="LONG",
                    open_time=datetime(2026, 8, 23, 23, 50, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 24, 0, 10, tzinfo=timezone.utc),
                    pnl=-0.4,
                ),
                Trade(
                    symbol="ETH/USDT",
                    side="SHORT",
                    open_time=datetime(2026, 8, 24, 1, 0, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 24, 1, 20, tzinfo=timezone.utc),
                    pnl=0.3,
                ),
                Trade(
                    symbol="SOL/USDT",
                    side="LONG",
                    open_time=datetime(2026, 8, 24, 2, 0, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 24, 2, 20, tzinfo=timezone.utc),
                    pnl=-0.2,
                ),
                Trade(
                    symbol="XRP/USDT",
                    side="LONG",
                    open_time=datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc),
                    close_time=datetime(2026, 8, 24, 3, 20, tzinfo=timezone.utc),
                    pnl=-0.2,
                ),
            ]
        )
        db.commit()

        assert consecutive_losses_for_utc_day(db, date(2026, 8, 23)) == 1
        assert consecutive_losses_for_utc_day(db, date(2026, 8, 24)) == 2
        assert consecutive_losses_for_utc_day(db, date(2026, 8, 25)) == 0
    finally:
        db.close()
