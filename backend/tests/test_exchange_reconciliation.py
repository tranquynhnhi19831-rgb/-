from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models.database import Base
from models.position import Position
from models.trade import Trade
from services.exchange_reconciliation import reconcile_local_with_demo


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _snapshot(*, positions=None, orders=None):
    return {
        "environment": "TESTNET",
        "binance_mode": "DEMO_TRADING",
        "positions": positions or [],
        "open_orders": orders or [],
    }


def _add_local_open(db, *, symbol="BTC/USDT", side="LONG", quantity=0.05):
    db.add(
        Trade(
            symbol=symbol,
            side=side,
            entry_price=100,
            quantity=quantity,
            stop_loss=99,
            take_profit=101.8,
            close_time=None,
        )
    )
    db.add(
        Position(
            symbol=symbol,
            side=side,
            entry_price=100,
            mark_price=100,
            quantity=quantity,
            leverage=3,
            is_open=True,
        )
    )
    db.commit()


def test_empty_local_and_empty_demo_are_reconciled():
    db = _db()
    try:
        result = reconcile_local_with_demo(db, _snapshot())
        assert result.ok is True
        assert result.errors == ()
    finally:
        db.close()


def test_matching_local_and_demo_position_are_reconciled():
    db = _db()
    try:
        _add_local_open(db)
        result = reconcile_local_with_demo(
            db,
            _snapshot(
                positions=[
                    {
                        "symbol": "BTC/USDT:USDT",
                        "side": "long",
                        "contracts": 0.05,
                        "entry_price": 100,
                        "leverage": 3,
                        "margin_mode": "isolated",
                    }
                ]
            ),
        )
        assert result.ok is True
        assert result.local_position["symbol"] == "BTC/USDT"
        assert result.exchange_position["side"] == "LONG"
    finally:
        db.close()


def test_demo_position_when_local_is_flat_fails_closed():
    db = _db()
    try:
        result = reconcile_local_with_demo(
            db,
            _snapshot(
                positions=[
                    {
                        "symbol": "BTC/USDT:USDT",
                        "side": "long",
                        "contracts": 0.05,
                        "entry_price": 100,
                        "leverage": 3,
                        "margin_mode": "isolated",
                    }
                ]
            ),
        )
        assert result.ok is False
        assert "LOCAL_DEMO_POSITION_COUNT_MISMATCH" in result.errors
    finally:
        db.close()


def test_symbol_side_and_quantity_mismatch_are_all_reported():
    db = _db()
    try:
        _add_local_open(db, symbol="BTC/USDT", side="LONG", quantity=0.05)
        result = reconcile_local_with_demo(
            db,
            _snapshot(
                positions=[
                    {
                        "symbol": "ETH/USDT:USDT",
                        "side": "short",
                        "contracts": 0.08,
                        "entry_price": 200,
                        "leverage": 3,
                        "margin_mode": "isolated",
                    }
                ]
            ),
        )
        assert result.ok is False
        assert "LOCAL_DEMO_POSITION_SYMBOL_MISMATCH" in result.errors
        assert "LOCAL_DEMO_POSITION_SIDE_MISMATCH" in result.errors
        assert "LOCAL_DEMO_POSITION_QUANTITY_MISMATCH" in result.errors
    finally:
        db.close()


def test_any_demo_open_order_is_unreconciled_until_exchange_order_state_is_persisted():
    db = _db()
    try:
        result = reconcile_local_with_demo(
            db,
            _snapshot(orders=[{"id": "1", "client_order_id": "jh_pending"}]),
        )
        assert result.ok is False
        assert "UNRECONCILED_DEMO_OPEN_ORDERS" in result.errors
        assert result.exchange_open_orders == 1
    finally:
        db.close()


def test_local_trade_position_disagreement_is_reported_even_before_exchange_compare():
    db = _db()
    try:
        db.add(
            Trade(
                symbol="BTC/USDT",
                side="LONG",
                entry_price=100,
                quantity=0.05,
                close_time=None,
            )
        )
        db.add(
            Position(
                symbol="ETH/USDT",
                side="SHORT",
                entry_price=100,
                quantity=0.08,
                is_open=True,
            )
        )
        db.commit()
        result = reconcile_local_with_demo(
            db,
            _snapshot(
                positions=[
                    {
                        "symbol": "ETH/USDT:USDT",
                        "side": "short",
                        "contracts": 0.08,
                        "entry_price": 100,
                        "leverage": 3,
                        "margin_mode": "isolated",
                    }
                ]
            ),
        )
        assert result.ok is False
        assert "LOCAL_POSITION_TRADE_SYMBOL_MISMATCH" in result.errors
        assert "LOCAL_POSITION_TRADE_SIDE_MISMATCH" in result.errors
        assert "LOCAL_POSITION_TRADE_QUANTITY_MISMATCH" in result.errors
    finally:
        db.close()
