from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from models.database import Base


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id = Column(Integer, primary_key=True, index=True)
    rule = Column(String, nullable=False)
    symbol = Column(String, default="")
    action = Column(String, default="blocked")
    reason = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
