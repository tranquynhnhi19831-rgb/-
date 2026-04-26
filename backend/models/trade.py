from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from models.database import Base


class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    open_time = Column(DateTime(timezone=True), server_default=func.now())
    close_time = Column(DateTime(timezone=True), nullable=True)
    entry_price = Column(Float, default=0)
    exit_price = Column(Float, default=0)
    stop_loss = Column(Float, default=0)
    take_profit = Column(Float, default=0)
    quantity = Column(Float, default=0)
    leverage = Column(Integer, default=1)
    fee = Column(Float, default=0)
    pnl = Column(Float, default=0)
    dry_run = Column(Boolean, default=True)
    reason = Column(Text, default="")
    deepseek_summary = Column(Text, default="")
