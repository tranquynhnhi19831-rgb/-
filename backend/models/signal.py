from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from sqlalchemy.sql import func
from models.database import Base


class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    timeframe = Column(String, default="15m")
    signal_type = Column(String, nullable=False)
    score = Column(Float, default=0)
    details = Column(Text, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
