from pathlib import Path
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "trading.db"
DB_URL = f"sqlite:///{DB_PATH}"

ALLOWED_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "DOGE/USDT",
    "XRP/USDT",
    "ARB/USDT",
]

# v1.1 small-account baseline. These are safety defaults, not claims of an
# optimal strategy. Backtests and paper/testnet results should decide whether
# they are changed later.
REFERENCE_CAPITAL_USDT = 100.0
DEFAULT_MAX_LEVERAGE = 3
HARD_MAX_LEVERAGE = 5
DEFAULT_RISK_PER_TRADE = 0.005
HARD_MAX_RISK_PER_TRADE = 0.01
DEFAULT_MAX_DAILY_LOSS = 0.02
HARD_MAX_DAILY_LOSS = 0.03


class AppConfig(BaseModel):
    binance_api_key: str = ""
    binance_secret: str = ""
    deepseek_api_key: str = ""
    testnet: bool = True
    dry_run: bool = True
    live_confirmed: bool = False
    margin_mode: str = "isolated"
    default_leverage: int = 1
    max_leverage: int = DEFAULT_MAX_LEVERAGE
    risk_per_trade: float = DEFAULT_RISK_PER_TRADE
    max_margin_per_trade: float = 0.10
    max_daily_loss: float = DEFAULT_MAX_DAILY_LOSS
    max_trades_per_day: int = 3
    max_open_positions: int = 1
    max_consecutive_losses: int = 3
    enabled_symbols: list[str] = Field(default_factory=lambda: ["BTC/USDT", "ETH/USDT"])


DEFAULT_CONFIG = AppConfig()
