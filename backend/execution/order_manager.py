from datetime import datetime
from models.trade import Trade
from models.position import Position


class OrderManager:
    def execute(self, db, cfg: dict, signal: dict, price: float, qty: float, stop: float, take: float, reason: str, deepseek_summary: str) -> Trade:
        trade = Trade(
            symbol=signal["symbol"],
            side=signal["signal_type"],
            entry_price=price,
            exit_price=price,
            stop_loss=stop,
            take_profit=take,
            quantity=qty,
            leverage=cfg["default_leverage"],
            fee=price * qty * 0.0004,
            pnl=0,
            dry_run=cfg["dry_run"],
            reason=reason,
            deepseek_summary=deepseek_summary,
            close_time=datetime.utcnow(),
        )
        db.add(trade)

        db.query(Position).filter(Position.is_open.is_(True)).update({"is_open": False})
        pos = Position(
            symbol=signal["symbol"],
            side=signal["signal_type"],
            entry_price=price,
            mark_price=price,
            quantity=qty,
            leverage=cfg["default_leverage"],
            unrealized_pnl=0,
            is_open=True,
        )
        db.add(pos)
        db.commit()
        db.refresh(trade)
        return trade
