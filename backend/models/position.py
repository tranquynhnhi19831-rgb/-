from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from sqlalchemy.sql import func
from models.database import Base


class Position(Base):
    __tablename__ = "positions"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    entry_price = Column(Float, default=0)
    mark_price = Column(Float, default=0)
    quantity = Column(Float, default=0)
    leverage = Column(Integer, default=1)
    unrealized_pnl = Column(Float, default=0)
    is_open = Column(Boolean, default=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
