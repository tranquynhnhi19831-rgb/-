from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func

from config import DEFAULT_CONFIG, REFERENCE_CAPITAL_USDT
from models.account_snapshot import AccountSnapshot
from models.config_model import ConfigModel
from models.position import Position
from models.risk_event import RiskEvent
from models.signal import Signal
from models.trade import Trade
from risk.risk_manager import RiskContext, RiskManager
from services.account_service import latest_account
from services.log_service import add_log
from services.paper_scenarios import scenario_for_index


class TradingEngine:
    """Local deterministic Paper engine for validating the Jianghe pipeline.

    This engine never talks to Binance and refuses to run when dry_run is off.
    The local scenarios are synthetic validation fixtures, not market data and
    not profitability evidence. They exist only to exercise strategy -> risk ->
    paper position -> close -> dashboard end-to-end before Demo API access.
    """

    def __init__(self) -> None:
        self.running = False
        self.risk = RiskManager()

    @staticmethod
    def _ensure_config(db) -> ConfigModel:
        cfg = db.query(ConfigModel).first()
        if cfg:
            return cfg
        d = DEFAULT_CONFIG.model_dump()
        cfg = ConfigModel(**{**d, "enabled_symbols": ",".join(d["enabled_symbols"])})
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
        return cfg

    @staticmethod
    def _config_dict(cfg: ConfigModel) -> dict:
        return {
            "dry_run": cfg.dry_run,
            "testnet": cfg.testnet,
            "margin_mode": cfg.margin_mode,
            "default_leverage": cfg.default_leverage,
            "max_leverage": cfg.max_leverage,
            "risk_per_trade": cfg.risk_per_trade,
            "max_margin_per_trade": cfg.max_margin_per_trade,
            "max_daily_loss": cfg.max_daily_loss,
            "max_trades_per_day": cfg.max_trades_per_day,
            "max_open_positions": cfg.max_open_positions,
            "max_consecutive_losses": cfg.max_consecutive_losses,
            "enabled_symbols": [s.strip() for s in cfg.enabled_symbols.split(",") if s.strip()],
        }

    @staticmethod
    def _consecutive_losses(db) -> int:
        trades = (
            db.query(Trade)
            .filter(Trade.close_time.isnot(None))
            .order_by(desc(Trade.id))
            .limit(20)
            .all()
        )
        count = 0
        for trade in trades:
            if float(trade.pnl or 0.0) < 0:
                count += 1
            else:
                break
        return count

    @staticmethod
    def _latest_open_trade(db, symbol: str) -> Trade | None:
        return (
            db.query(Trade)
            .filter(Trade.symbol == symbol, Trade.close_time.is_(None))
            .order_by(desc(Trade.id))
            .first()
        )

    def _close_existing_paper_position(self, db, position: Position) -> dict:
        trade = self._latest_open_trade(db, position.symbol)
        if trade is None:
            position.is_open = False
            db.commit()
            return {"action": "RECONCILE_ORPHAN_POSITION", "symbol": position.symbol}

        # Alternate a target exit and a stop exit so the local dashboard can
        # exercise both winning and losing accounting paths deterministically.
        use_target = (trade.id % 2) == 1
        exit_price = float(trade.take_profit if use_target else trade.stop_loss)
        entry = float(trade.entry_price)
        qty = float(trade.quantity)
        direction = 1.0 if str(trade.side).upper() in {"LONG", "BUY"} else -1.0
        gross = (exit_price - entry) * qty * direction
        fee = (abs(entry * qty) + abs(exit_price * qty)) * 0.0004
        net = gross - fee

        trade.exit_price = exit_price
        trade.fee = fee
        trade.pnl = net
        trade.close_time = datetime.now(timezone.utc)
        position.mark_price = exit_price
        position.unrealized_pnl = 0.0
        position.is_open = False

        previous = latest_account(db)
        balance = float(previous["balance"]) + net
        total_pnl = float(previous["total_pnl"]) + net
        daily_pnl = float(previous["daily_pnl"]) + net
        drawdown = max(0.0, (REFERENCE_CAPITAL_USDT - balance) / REFERENCE_CAPITAL_USDT)
        db.add(
            AccountSnapshot(
                equity=balance,
                balance=balance,
                daily_pnl=daily_pnl,
                total_pnl=total_pnl,
                max_drawdown=max(float(previous["max_drawdown"]), drawdown),
            )
        )
        db.commit()
        add_log(
            db,
            f"PAPER平仓 {position.symbol} {trade.side} exit={exit_price:.4f} netPnL={net:.4f}U",
            "INFO",
            "paper",
        )
        return {
            "action": "CLOSE_PAPER_POSITION",
            "source": "DETERMINISTIC_PAPER_SCENARIO",
            "symbol": position.symbol,
            "side": trade.side,
            "exit": exit_price,
            "net_pnl_usdt": net,
            "outcome": "TARGET" if use_target else "STOP",
        }

    async def start_once(self, db) -> dict:
        cfg = self._ensure_config(db)
        cfg_dict = self._config_dict(cfg)

        if not cfg_dict["dry_run"]:
            self.running = False
            raise RuntimeError("Local Jianghe Paper Engine requires dry_run=true; Binance/Mainnet execution is not available here")

        open_position = (
            db.query(Position)
            .filter(Position.is_open.is_(True))
            .order_by(desc(Position.id))
            .first()
        )
        if open_position is not None:
            return self._close_existing_paper_position(db, open_position)

        account = latest_account(db)
        trades_today = db.query(Trade).filter(func.date(Trade.open_time) == datetime.utcnow().date()).count()
        open_positions = db.query(Position).filter(Position.is_open.is_(True)).count()
        consecutive_losses = self._consecutive_losses(db)

        enabled = cfg_dict["enabled_symbols"] or ["BTC/USDT"]
        symbol = enabled[0]
        historical_trade_count = db.query(Trade).count()
        scenario = scenario_for_index(historical_trade_count, symbol)
        evaluation = scenario.evaluation

        if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
            add_log(db, f"PAPER场景未形成候选: {scenario.name}", "WARNING", "paper")
            return {
                "action": "NO_CANDIDATE",
                "source": "DETERMINISTIC_PAPER_SCENARIO",
                "setup": scenario.name,
                "reason_codes": list(evaluation.reason_codes),
            }

        entry = float(evaluation.entry_reference)
        stop = float(evaluation.invalidation_reference)
        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            raise RuntimeError("Paper candidate has invalid structural stop distance")

        leverage = int(cfg.default_leverage)
        ctx = RiskContext(
            equity=float(account["equity"]),
            daily_pnl=float(account["daily_pnl"]),
            trades_today=trades_today,
            open_positions=open_positions,
            consecutive_losses=consecutive_losses,
        )
        allowed, reason = self.risk.check(
            cfg_dict,
            ctx,
            symbol,
            rr=1.8,
            leverage=leverage,
            margin_ratio=min(0.05, float(cfg.max_margin_per_trade)),
        )
        if not allowed:
            db.add(RiskEvent(rule="paper_risk_check", symbol=symbol, action="blocked", reason=reason))
            db.commit()
            add_log(db, f"PAPER风控拦截 {symbol}: {reason}", "WARNING", "paper")
            return {"action": "RISK_BLOCKED", "symbol": symbol, "reason": reason}

        risk_budget = self.risk.risk_budget_usdt(cfg_dict, float(account["equity"]))
        qty_by_stop = risk_budget / stop_distance
        max_notional = float(account["equity"]) * float(cfg.max_margin_per_trade) * leverage
        qty_by_notional = max_notional / max(entry, 1e-9)
        quantity = min(qty_by_stop, qty_by_notional)
        if quantity <= 0:
            raise RuntimeError("Paper position size resolved to zero")

        side = str(evaluation.side).upper()
        direction = 1.0 if side == "LONG" else -1.0
        take = entry + direction * stop_distance * 1.8
        reason_codes = list(evaluation.reason_codes)
        reason_text = f"PAPER:{scenario.name}; " + ",".join(reason_codes)

        db.add(
            Signal(
                symbol=symbol,
                timeframe="LOCAL_SCENARIO",
                signal_type=side,
                score=1.0,
                details=reason_text,
            )
        )
        trade = Trade(
            symbol=symbol,
            side=side,
            entry_price=entry,
            exit_price=0.0,
            stop_loss=stop,
            take_profit=take,
            quantity=quantity,
            leverage=leverage,
            fee=abs(entry * quantity) * 0.0004,
            pnl=0.0,
            dry_run=True,
            reason=reason_text,
            deepseek_summary="LOCAL_PAPER_NO_LLM",
            close_time=None,
        )
        db.add(trade)
        db.add(
            Position(
                symbol=symbol,
                side=side,
                entry_price=entry,
                mark_price=entry,
                quantity=quantity,
                leverage=leverage,
                unrealized_pnl=0.0,
                is_open=True,
            )
        )
        db.commit()
        add_log(
            db,
            f"PAPER开仓 {symbol} {side} setup={scenario.name} entry={entry:.4f} stop={stop:.4f} take={take:.4f}",
            "INFO",
            "paper",
        )
        return {
            "action": "OPEN_PAPER_POSITION",
            "source": "DETERMINISTIC_PAPER_SCENARIO",
            "symbol": symbol,
            "setup": scenario.name,
            "side": side,
            "entry": entry,
            "stop": stop,
            "take": take,
            "quantity": quantity,
            "risk_budget_usdt": risk_budget,
            "max_notional_usdt": max_notional,
            "reason_codes": reason_codes,
        }


ENGINE = TradingEngine()
