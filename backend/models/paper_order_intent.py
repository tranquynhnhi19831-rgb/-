from __future__ import annotations

from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.sql import func

from models.database import Base


class PaperOrderIntent(Base):
    """Persistent next-bar Paper order intent.

    A strategy signal is known only after its candle closes. To preserve the
    backtest convention, autonomous Paper does not immediately fill at that same
    close. It stores a PENDING intent and can fill it from the next 1m bar open.
    This table also lets a process restart recover or expire an intent safely.
    """

    __tablename__ = "paper_order_intents"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(String, nullable=False, unique=True, index=True)
    cycle_id = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    setup = Column(String, nullable=False)
    side = Column(String, nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    signal_close_time = Column(DateTime(timezone=True), nullable=False, index=True)
    stop_reference = Column(Float, nullable=False)
    reward_risk = Column(Float, nullable=False, default=1.8)
    status = Column(String, nullable=False, default="PENDING", index=True)
    reason_codes_json = Column(Text, nullable=False, default="[]")
    evidence_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    filled_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(String, nullable=False, default="")
