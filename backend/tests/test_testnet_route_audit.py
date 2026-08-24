import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api.routes_testnet as routes
from models.database import Base
from models.trade_decision import TradeDecision


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class OrderTestGateway:
    def test_market_order(self, **kwargs):
        return {
            "ok": True,
            "creates_order": False,
            "preview": {
                "quantity": 0.001,
                "actual_notional_usdt": 10.0,
            },
        }


def test_order_test_writes_intent_and_validated_lifecycle(monkeypatch):
    db = _db()
    monkeypatch.setattr(routes, "_gateway", lambda: OrderTestGateway())
    try:
        result = routes.testnet_order_test(
            {
                "symbol": "BTC/USDT",
                "side": "BUY",
                "target_notional_usdt": 10.0,
                "client_order_id": "jh-test-001",
                "confirm": "TESTNET_ORDER_TEST",
            },
            db,
        )

        assert result["creates_order"] is False
        rows = db.query(TradeDecision).order_by(TradeDecision.id).all()
        assert [row.stage for row in rows] == ["ORDER_INTENT", "ORDER_TEST"]
        assert [row.outcome for row in rows] == ["TEST_REQUESTED", "VALIDATED"]
        assert rows[0].decision_id == rows[1].decision_id == result["decision_id"]
        assert json.loads(rows[1].reason_codes_json) == ["SIGNED_REQUEST_ACCEPTED", "NO_ORDER_CREATED"]
    finally:
        db.close()


def test_disabled_demo_market_order_is_audited_before_403(monkeypatch):
    db = _db()
    monkeypatch.setattr(routes, "_orders_enabled", lambda: False)
    try:
        with pytest.raises(HTTPException) as exc:
            routes.testnet_market_order(
                {
                    "symbol": "BTC/USDT",
                    "side": "BUY",
                    "target_notional_usdt": 10.0,
                    "client_order_id": "jh-demo-001",
                    "confirm": "PLACE_TESTNET_ORDER",
                },
                db,
            )

        assert exc.value.status_code == 403
        rows = db.query(TradeDecision).order_by(TradeDecision.id).all()
        assert [row.stage for row in rows] == ["ORDER_INTENT", "EXECUTION_GATE"]
        assert rows[-1].outcome == "BLOCKED"
        assert rows[-1].risk_code == "TESTNET_ORDER_ROUTES_DISABLED"
    finally:
        db.close()
