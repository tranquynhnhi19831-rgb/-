from sqlalchemy import Column, Integer, Float, DateTime
from sqlalchemy.sql import func
from models.database import Base


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    id = Column(Integer, primary_key=True, index=True)
    equity = Column(Float, default=20)
    balance = Column(Float, default=20)
    daily_pnl = Column(Float, default=0)
    total_pnl = Column(Float, default=0)
    max_drawdown = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
