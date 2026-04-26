from datetime import datetime
from sqlalchemy import func
from models.config_model import ConfigModel
from models.signal import Signal
from models.trade import Trade
from models.position import Position
from models.risk_event import RiskEvent
from services.market_data_service import fake_ohlcv
from strategy.n_pattern_strategy import generate_signal
from risk.risk_manager import RiskManager, RiskContext
from execution.order_manager import OrderManager
from services.deepseek_service import DeepSeekService
from services.log_service import add_log
from services.account_service import latest_account


class TradingEngine:
    def __init__(self) -> None:
        self.running = False
        self.risk = RiskManager()
        self.order_mgr = OrderManager()
        self.deepseek = DeepSeekService()

    async def start_once(self, db) -> None:
        cfg = db.query(ConfigModel).first()
        if not cfg:
            return
        cfg_dict = {
            c: getattr(cfg, c)
            for c in [
                "dry_run",
                "testnet",
                "margin_mode",
                "default_leverage",
                "max_leverage",
                "risk_per_trade",
                "max_margin_per_trade",
                "max_daily_loss",
                "max_trades_per_day",
                "max_open_positions",
                "max_consecutive_losses",
            ]
        }
        cfg_dict["enabled_symbols"] = [s.strip() for s in cfg.enabled_symbols.split(",") if s.strip()]

        account = latest_account(db)
        trades_today = db.query(Trade).filter(func.date(Trade.open_time) == datetime.utcnow().date()).count()
        open_positions = db.query(Position).filter(Position.is_open.is_(True)).count()
        consecutive_losses = 0

        for symbol in cfg_dict["enabled_symbols"]:
            h1 = fake_ohlcv(320)
            m15 = fake_ohlcv(200, seed=len(symbol) + 7)
            signal = generate_signal(symbol, h1, m15)
            if not signal:
                continue

            db.add(Signal(symbol=symbol, timeframe="15m", signal_type=signal["signal_type"], score=signal["score"], details=signal["reason"]))
            db.commit()

            ctx = RiskContext(
                equity=account["equity"],
                daily_pnl=account["daily_pnl"],
                trades_today=trades_today,
                open_positions=open_positions,
                consecutive_losses=consecutive_losses,
            )
            allowed, reason = self.risk.check(cfg_dict, ctx, symbol, rr=1.8, leverage=cfg.default_leverage, margin_ratio=0.05)
            if not allowed:
                db.add(RiskEvent(rule="risk_check", symbol=symbol, action="blocked", reason=reason))
                db.commit()
                add_log(db, f"风控拦截 {symbol}: {reason}", "WARNING", "risk")
                continue

            ds = await self.deepseek.summarize_signal(cfg.deepseek_api_key, signal)
            self.order_mgr.execute(db, cfg_dict, signal, price=float(m15['close'].iloc[-1]), qty=0.01, stop=float(m15['close'].iloc[-1] * 0.99), take=float(m15['close'].iloc[-1] * 1.02), reason=signal['reason'], deepseek_summary=ds)
            add_log(db, f"执行{'模拟' if cfg_dict['dry_run'] else '真实'}订单: {symbol} {signal['signal_type']}", "INFO", "trading")
            break


ENGINE = TradingEngine()
