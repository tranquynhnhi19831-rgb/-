from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from models.database import Base


class TradeDecision(Base):
    """Structured audit trail for every strategy order intent and its lifecycle.

    A strategy decision can be blocked by risk, skipped by global arbitration,
    rejected by the exchange, or never fill. Those events still need to remain
    queryable even when no row is ever created in ``trades``.
    """

    __tablename__ = "trade_decisions"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(String, nullable=False, index=True, default=lambda: uuid.uuid4().hex)
    cycle_id = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    setup = Column(String, nullable=False, default="")
    side = Column(String, nullable=False, default="")

    stage = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False, index=True)
    candidate = Column(Boolean, nullable=False, default=False)
    selected = Column(Boolean, nullable=False, default=False)

    score = Column(Float, nullable=True)
    entry_reference = Column(Float, nullable=True)
    stop_reference = Column(Float, nullable=True)
    target_reference = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    planned_risk_usdt = Column(Float, nullable=True)
    planned_notional_usdt = Column(Float, nullable=True)

    reason_codes_json = Column(Text, nullable=False, default="[]")
    evidence_json = Column(Text, nullable=False, default="{}")
    risk_code = Column(String, nullable=False, default="")
    risk_message = Column(Text, nullable=False, default="")
    client_order_id = Column(String, nullable=False, default="")
    exchange_order_id = Column(String, nullable=False, default="")
    trade_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
