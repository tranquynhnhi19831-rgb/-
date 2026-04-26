from sqlalchemy import Column, Integer, String, Boolean, Float, Text
from models.database import Base


class ConfigModel(Base):
    __tablename__ = "config"
    id = Column(Integer, primary_key=True, index=True)
    binance_api_key = Column(String, default="")
    binance_secret = Column(String, default="")
    deepseek_api_key = Column(String, default="")
    testnet = Column(Boolean, default=True)
    dry_run = Column(Boolean, default=True)
    live_confirmed = Column(Boolean, default=False)
    margin_mode = Column(String, default="isolated")
    default_leverage = Column(Integer, default=1)
    max_leverage = Column(Integer, default=5)
    risk_per_trade = Column(Float, default=0.01)
    max_margin_per_trade = Column(Float, default=0.10)
    max_daily_loss = Column(Float, default=0.03)
    max_trades_per_day = Column(Integer, default=3)
    max_open_positions = Column(Integer, default=1)
    max_consecutive_losses = Column(Integer, default=3)
    enabled_symbols = Column(Text, default="BTC/USDT,ETH/USDT")
