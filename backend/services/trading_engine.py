from __future__ import annotations

import asyncio
from datetime import datetime, UTC
from sqlalchemy import func, desc
from models.config_model import ConfigModel
from models.signal import Signal
from models.trade import Trade
from models.position import Position
from models.risk_event import RiskEvent
from models.log import Log
from services.market_data_service import fetch_ohlcv_df
from strategy.n_pattern_strategy import generate_signal
from risk.risk_manager import RiskManager, RiskContext
from execution.order_manager import OrderManager
from services.deepseek_service import DeepSeekService
from services.log_service import add_log
from exchange.binance_client import BinanceClient
from services.account_service import build_account_state


class TradingEngine:
    def __init__(self) -> None:
        self.running = False
        self.task: asyncio.Task | None = None
        self.risk = RiskManager()
        self.order_mgr = OrderManager()
        self.deepseek = DeepSeekService()
        self.error_count = 0
        self.max_errors = 5
        self.last_market_update: str | None = None
        self.last_account_state: dict = {}

    def _cfg_dict(self, cfg: ConfigModel) -> dict:
        out = {c: getattr(cfg, c) for c in [
            "binance_api_key", "binance_secret", "deepseek_api_key", "deepseek_base_url", "deepseek_model",
            "dry_run", "testnet", "live_confirmed", "margin_mode", "default_leverage", "max_leverage", "risk_per_trade",
            "max_margin_per_trade", "max_daily_loss", "max_trades_per_day", "max_open_positions", "max_consecutive_losses",
            "cooldown_seconds", "loop_interval_seconds"
        ]}
        out["enabled_symbols"] = [s.strip() for s in cfg.enabled_symbols.split(",") if s.strip()]
        return out

    async def _loop(self, session_factory):
        add_log(session_factory(), "交易循环已启动", "INFO", "system")
        while self.running:
            db = session_factory()
            try:
                cfg = db.query(ConfigModel).first()
                if not cfg:
                    add_log(db, "配置为空，跳过本轮", "WARNING", "system")
                    await asyncio.sleep(5)
                    continue
                cfg_dict = self._cfg_dict(cfg)
                await self._run_once(db, cfg_dict)
                self.error_count = 0
            except Exception as exc:
                self.error_count += 1
                add_log(db, f"交易循环异常: {exc}", "ERROR", "system")
                if self.error_count >= self.max_errors:
                    self.running = False
                    add_log(db, "连续API错误达到阈值，系统自动停止", "ERROR", "risk")
            finally:
                db.close()
            await asyncio.sleep(max(cfg_dict.get("loop_interval_seconds", 60), 30) if 'cfg_dict' in locals() else 30)

    async def start(self, session_factory) -> tuple[bool, str]:
        if self.running and self.task and not self.task.done():
            return False, "交易循环已在运行"
        self.running = True
        self.task = asyncio.create_task(self._loop(session_factory))
        return True, "已启动"

    async def stop(self) -> tuple[bool, str]:
        self.running = False
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except Exception:
                pass
        return True, "已停止"

    async def _run_once(self, db, cfg_dict: dict) -> None:
        client = None
        if cfg_dict["binance_api_key"] and cfg_dict["binance_secret"]:
            client = BinanceClient(cfg_dict["binance_api_key"], cfg_dict["binance_secret"], cfg_dict["testnet"])

        account = build_account_state(cfg_dict, db, client)
        self.last_account_state = account

        trades_today = db.query(Trade).filter(func.date(Trade.open_time) == datetime.now(UTC).date()).count()
        open_positions_count = db.query(Position).filter(Position.is_open.is_(True)).count()
        last_trade = db.query(Trade).order_by(desc(Trade.id)).first()
        seconds_since_last_trade = 999999 if not last_trade else int((datetime.now(UTC) - last_trade.open_time.replace(tzinfo=UTC)).total_seconds())

        if not cfg_dict["enabled_symbols"]:
            add_log(db, "无启用交易对", "WARNING", "strategy")
            return

        for symbol in cfg_dict["enabled_symbols"]:
            if client is None:
                add_log(db, f"{symbol} 跳过：未配置 Binance API，避免伪行情交易", "WARNING", "market")
                continue
            try:
                h1 = fetch_ohlcv_df(client, symbol, "1h", 300)
                m15 = fetch_ohlcv_df(client, symbol, "15m", 300)
                self.last_market_update = datetime.now(UTC).isoformat()
            except Exception as exc:
                add_log(db, f"行情拉取失败 {symbol}: {exc}", "ERROR", "market")
                self.error_count += 1
                continue

            signal = generate_signal(symbol, h1, m15)
            if not signal:
                continue

            db.add(Signal(symbol=symbol, timeframe=signal["timeframe"], signal_type=signal["side"], score=signal["score"], details=signal["reason"]))
            db.commit()

            market = client.market(symbol)
            market_limits = {
                "amount": (market.get("limits") or {}).get("amount") or {},
                "cost": (market.get("limits") or {}).get("cost") or {},
                "amount_precision": (market.get("precision") or {}).get("amount") or 3,
                "price_precision": (market.get("precision") or {}).get("price") or 2,
            }

            ctx = RiskContext(
                equity=float(account["equity"]),
                daily_pnl=float(account.get("daily_pnl", 0)),
                trades_today=trades_today,
                open_positions=open_positions_count,
                consecutive_losses=0,
                has_open_orders=len(account.get("open_orders", [])) > 0,
                has_same_side_position=any((p.get("symbol") == symbol.replace('/', '') and ((float(p.get("contracts") or 0) > 0 and signal["side"] == "long") or (float(p.get("contracts") or 0) < 0 and signal["side"] == "short"))) for p in account.get("positions", [])),
                has_opposite_position=any((p.get("symbol") == symbol.replace('/', '') and ((float(p.get("contracts") or 0) > 0 and signal["side"] == "short") or (float(p.get("contracts") or 0) < 0 and signal["side"] == "long"))) for p in account.get("positions", [])),
                seconds_since_last_trade=seconds_since_last_trade,
                volatility_ratio=float((m15["high"].iloc[-1] - m15["low"].iloc[-1]) / max(m15["close"].iloc[-1], 1e-9)),
            )
            allowed, reason, plan = self.risk.check(cfg_dict, ctx, symbol, signal, market_limits)
            if not allowed:
                db.add(RiskEvent(rule="risk_check", symbol=symbol, action="blocked", reason=reason))
                db.commit()
                add_log(db, f"风控拦截 {symbol}: {reason}", "WARNING", "risk")
                continue

            ds = await self.deepseek.summarize_signal(
                cfg_dict["deepseek_api_key"],
                cfg_dict["deepseek_base_url"],
                cfg_dict["deepseek_model"],
                signal,
                market_summary=f"1h close={h1['close'].iloc[-1]}, 15m close={m15['close'].iloc[-1]}",
                risk_summary="风控通过",
            )
            signal["deepseek_summary"] = ds
            add_log(db, f"DeepSeek摘要: {ds}", "INFO", "deepseek")

            ok, msg, _ = self.order_mgr.execute(db, cfg_dict, signal, plan, client)
            if not ok:
                add_log(db, f"执行失败: {msg}", "ERROR", "execution")
            return

    def snapshot(self, db) -> dict:
        last_signal = db.query(Signal).order_by(desc(Signal.id)).first()
        last_risk = db.query(RiskEvent).order_by(desc(RiskEvent.id)).first()
        logs = db.query(Log).order_by(desc(Log.id)).limit(20).all()
        positions = db.query(Position).filter(Position.is_open.is_(True)).order_by(desc(Position.id)).limit(10).all()
        return {
            "running": self.running,
            "last_market_update": self.last_market_update,
            "account": self.last_account_state,
            "positions": [p.__dict__ | {"_sa_instance_state": None} for p in positions],
            "last_signal": None if not last_signal else last_signal.__dict__ | {"_sa_instance_state": None},
            "last_risk_event": None if not last_risk else last_risk.__dict__ | {"_sa_instance_state": None},
            "logs": [l.__dict__ | {"_sa_instance_state": None} for l in logs],
        }


ENGINE = TradingEngine()
