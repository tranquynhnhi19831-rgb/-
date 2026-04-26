from pathlib import Path
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "trading.db"
DB_URL = f"sqlite:///{DB_PATH}"
ALLOWED_SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "DOGE/USDT", "XRP/USDT", "ARB/USDT"]


class AppConfig(BaseModel):
    binance_api_key: str = ""
    binance_secret: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    testnet: bool = True
    dry_run: bool = True
    live_confirmed: bool = False
    margin_mode: str = "isolated"
    default_leverage: int = 1
    max_leverage: int = 5
    risk_per_trade: float = 0.01
    max_margin_per_trade: float = 0.10
    max_daily_loss: float = 0.03
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    max_consecutive_losses: int = 3
    cooldown_seconds: int = 300
    loop_interval_seconds: int = 60
    enabled_symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])


DEFAULT_CONFIG = AppConfig()
