from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from models.database import Base


class RuntimeState(Base):
    """Singleton control plane state for autonomous workers.

    The row is intentionally separate from trading configuration. A stale or
    duplicated worker must not be able to infer permission to trade merely from
    strategy settings. `kill_switch=True` always wins.
    """

    __tablename__ = "runtime_state"

    id = Column(Integer, primary_key=True, default=1)
    mode = Column(String, nullable=False, default="PAPER")
    kill_switch = Column(Boolean, nullable=False, default=True)
    lease_owner = Column(String, nullable=False, default="")
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    last_cycle_id = Column(String, nullable=False, default="")
    last_error = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
