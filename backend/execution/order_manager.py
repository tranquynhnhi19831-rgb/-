from __future__ import annotations

from datetime import datetime
from models.trade import Trade
from models.position import Position
from services.log_service import add_log
from models.risk_event import RiskEvent


class OrderManager:
    def execute(self, db, cfg: dict, signal: dict, execution_plan: dict, binance_client=None) -> tuple[bool, str, Trade | None]:
        if not signal.get("stop_loss") or not signal.get("take_profit"):
            db.add(RiskEvent(rule="order", symbol=signal["symbol"], action="blocked", reason="禁止无止损止盈订单"))
            db.commit()
            return False, "禁止无止损止盈订单", None

        symbol = signal["symbol"]
        side = signal["side"]
        entry = execution_plan["entry"]
        qty = execution_plan["qty"]

        exchange_order_id = "dry-run"
        if cfg["dry_run"]:
            add_log(db, f"DRY-RUN 模拟下单 {symbol} {side} qty={qty}", "INFO", "execution")
        else:
            if cfg["testnet"]:
                mode = "TESTNET"
            elif cfg["live_confirmed"]:
                mode = "LIVE"
            else:
                return False, "live 模式未确认", None

            try:
                if binance_client is None:
                    return False, "缺少交易所客户端", None
                order = binance_client.create_order(symbol, side, qty, execution_plan["stop_loss"], execution_plan["take_profit"])
                exchange_order_id = order.get("id", mode)
                add_log(db, f"{mode} 下单成功 {symbol} {side} id={exchange_order_id}", "INFO", "execution")
            except Exception as exc:
                db.add(RiskEvent(rule="order", symbol=symbol, action="failed", reason=str(exc)))
                db.commit()
                add_log(db, f"下单失败 {symbol}: {exc}", "ERROR", "execution")
                return False, str(exc), None

        trade = Trade(
            symbol=symbol,
            side=side,
            entry_price=entry,
            exit_price=entry,
            stop_loss=execution_plan["stop_loss"],
            take_profit=execution_plan["take_profit"],
            quantity=qty,
            leverage=cfg["default_leverage"],
            fee=execution_plan["estimated_fee"],
            pnl=0,
            dry_run=cfg["dry_run"],
            reason=signal["reason"],
            deepseek_summary=signal.get("deepseek_summary", ""),
            close_time=datetime.utcnow(),
        )
        db.add(trade)

        db.query(Position).filter(Position.is_open.is_(True)).update({"is_open": False})
        pos = Position(
            symbol=symbol,
            side=side,
            entry_price=entry,
            mark_price=entry,
            quantity=qty,
            leverage=cfg["default_leverage"],
            unrealized_pnl=0,
            is_open=True,
        )
        db.add(pos)
        db.commit()
        db.refresh(trade)
        return True, exchange_order_id, trade
