from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import desc, func

from config import DEFAULT_CONFIG, INITIAL_TRADING_UNIVERSE, REFERENCE_CAPITAL_USDT
from models.account_snapshot import AccountSnapshot
from models.config_model import ConfigModel
from models.position import Position
from models.risk_event import RiskEvent
from models.signal import Signal
from models.trade import Trade
from risk.risk_manager import RiskContext, RiskManager
from services.account_service import latest_account, realized_pnl_for_utc_day, trades_opened_on_utc_day
from services.log_service import add_log
from services.paper_scenarios import scenario_for_index
from services.trade_audit_service import (
    add_trade_decision,
    decision_id_for_trade,
    new_cycle_id,
    new_decision_id,
)


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
        fixed_symbols = ",".join(INITIAL_TRADING_UNIVERSE)
        if cfg:
            if cfg.enabled_symbols != fixed_symbols:
                cfg.enabled_symbols = fixed_symbols
                db.commit()
            return cfg
        d = DEFAULT_CONFIG.model_dump()
        cfg = ConfigModel(**{**d, "enabled_symbols": fixed_symbols})
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
            "enabled_symbols": list(INITIAL_TRADING_UNIVERSE),
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

    @staticmethod
    def _drawdown_fraction(peak_equity: float, current_equity: float) -> float:
        peak = max(float(peak_equity), 0.0)
        current = float(current_equity)
        if peak <= 0:
            return 0.0
        return max(0.0, (peak - current) / peak)

    @staticmethod
    def _historical_peak_equity(db) -> float:
        stored_peak = db.query(func.max(AccountSnapshot.equity)).scalar()
        return max(REFERENCE_CAPITAL_USDT, float(stored_peak or 0.0))

    def _close_existing_paper_position(self, db, position: Position, cycle_id: str) -> dict:
        trade = self._latest_open_trade(db, position.symbol)
        if trade is None:
            position.is_open = False
            db.commit()
            return {"action": "RECONCILE_ORPHAN_POSITION", "symbol": position.symbol}

        daily_pnl_before = realized_pnl_for_utc_day(db)

        # Alternate target/stop outcomes only for deterministic engineering
        # validation. Historical/real-time strategy exits use market data.
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
        daily_pnl = daily_pnl_before + net
        peak_equity = self._historical_peak_equity(db)
        drawdown = self._drawdown_fraction(peak_equity, balance)
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

        decision_id = decision_id_for_trade(db, trade.id)
        if decision_id:
            add_trade_decision(
                db,
                cycle_id=cycle_id,
                decision_id=decision_id,
                symbol=position.symbol,
                setup="PAPER_EXIT",
                side=str(trade.side),
                stage="EXIT",
                outcome="CLOSED",
                candidate=True,
                selected=True,
                entry_reference=entry,
                stop_reference=float(trade.stop_loss),
                target_reference=float(trade.take_profit),
                quantity=qty,
                reason_codes=["TARGET" if use_target else "STOP"],
                evidence={
                    "exit_price": exit_price,
                    "gross_pnl_usdt": gross,
                    "fee_usdt": fee,
                    "net_pnl_usdt": net,
                    "source": "DETERMINISTIC_PAPER_SCENARIO",
                },
                trade_id=trade.id,
            )

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
            "gross_pnl_usdt": gross,
            "fee_usdt": fee,
            "net_pnl_usdt": net,
            "outcome": "TARGET" if use_target else "STOP",
            "equity_peak_usdt": peak_equity,
            "drawdown_fraction": drawdown,
            "daily_pnl_usdt": daily_pnl,
            "decision_id": decision_id,
        }

    async def start_once(self, db) -> dict:
        cycle_id = new_cycle_id("paper")
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
            return self._close_existing_paper_position(db, open_position, cycle_id)

        account = latest_account(db)
        daily_pnl = realized_pnl_for_utc_day(db)
        trades_today = trades_opened_on_utc_day(db)
        open_positions = db.query(Position).filter(Position.is_open.is_(True)).count()
        consecutive_losses = self._consecutive_losses(db)
        equity = float(account["equity"])
        day_start_equity = max(0.0, equity - daily_pnl)

        # Synthetic Paper rotates through the fixed universe so engineering
        # validation does not silently exercise BTC only. The future autonomous
        # scanner evaluates all seven concurrently from real closed candles.
        historical_trade_count = db.query(Trade).count()
        symbol = INITIAL_TRADING_UNIVERSE[historical_trade_count % len(INITIAL_TRADING_UNIVERSE)]
        scenario = scenario_for_index(historical_trade_count, symbol)
        evaluation = scenario.evaluation

        if not evaluation.candidate or evaluation.side is None or evaluation.invalidation_reference is None:
            add_log(db, f"PAPER场景未形成候选: {scenario.name}", "WARNING", "paper")
            return {
                "action": "NO_CANDIDATE",
                "source": "DETERMINISTIC_PAPER_SCENARIO",
                "setup": scenario.name,
                "reason_codes": list(evaluation.reason_codes),
                "cycle_id": cycle_id,
            }

        entry = float(evaluation.entry_reference)
        stop = float(evaluation.invalidation_reference)
        stop_distance = abs(entry - stop)
        if stop_distance <= 0:
            raise RuntimeError("Paper candidate has invalid structural stop distance")

        side = str(evaluation.side).upper()
        direction = 1.0 if side == "LONG" else -1.0
        take = entry + direction * stop_distance * 1.8
        reason_codes = list(evaluation.reason_codes)
        reason_text = f"PAPER:{scenario.name}; " + ",".join(reason_codes)
        decision_id = new_decision_id()
        evaluation_dict = evaluation.to_dict() if hasattr(evaluation, "to_dict") else {}

        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup=scenario.name,
            side=side,
            stage="CANDIDATE",
            outcome="QUALIFIED",
            candidate=True,
            selected=True,
            score=1.0,
            entry_reference=entry,
            stop_reference=stop,
            target_reference=take,
            reason_codes=reason_codes,
            evidence={
                "source": "DETERMINISTIC_PAPER_SCENARIO",
                "evaluation": evaluation_dict,
                "equity_usdt": equity,
                "daily_pnl_usdt": daily_pnl,
                "trades_today": trades_today,
                "open_positions": open_positions,
                "consecutive_losses": consecutive_losses,
            },
        )

        leverage = int(cfg.default_leverage)
        ctx = RiskContext(
            equity=equity,
            daily_pnl=daily_pnl,
            trades_today=trades_today,
            open_positions=open_positions,
            consecutive_losses=consecutive_losses,
            day_start_equity=day_start_equity,
        )
        risk_decision = self.risk.evaluate(
            cfg_dict,
            ctx,
            symbol,
            rr=1.8,
            leverage=leverage,
            margin_ratio=min(0.05, float(cfg.max_margin_per_trade)),
        )
        if not risk_decision.allowed:
            db.add(RiskEvent(rule="paper_risk_check", symbol=symbol, action="blocked", reason=risk_decision.message))
            db.commit()
            add_trade_decision(
                db,
                cycle_id=cycle_id,
                decision_id=decision_id,
                symbol=symbol,
                setup=scenario.name,
                side=side,
                stage="RISK",
                outcome="BLOCKED",
                candidate=True,
                selected=True,
                score=1.0,
                entry_reference=entry,
                stop_reference=stop,
                target_reference=take,
                reason_codes=reason_codes,
                evidence={
                    "equity_usdt": equity,
                    "daily_pnl_usdt": daily_pnl,
                    "trades_today": trades_today,
                    "open_positions": open_positions,
                    "consecutive_losses": consecutive_losses,
                    "day_start_equity_usdt": day_start_equity,
                },
                risk_code=risk_decision.code,
                risk_message=risk_decision.message,
            )
            add_log(db, f"PAPER风控拦截 {symbol}: {risk_decision.code} {risk_decision.message}", "WARNING", "paper")
            return {
                "action": "RISK_BLOCKED",
                "symbol": symbol,
                "reason_code": risk_decision.code,
                "reason": risk_decision.message,
                "daily_pnl_usdt": daily_pnl,
                "trades_today": trades_today,
                "cycle_id": cycle_id,
                "decision_id": decision_id,
            }

        risk_budget = self.risk.risk_budget_usdt(cfg_dict, equity)
        qty_by_stop = risk_budget / stop_distance
        max_notional = equity * float(cfg.max_margin_per_trade) * leverage
        qty_by_notional = max_notional / max(entry, 1e-9)
        quantity = min(qty_by_stop, qty_by_notional)
        if quantity <= 0:
            raise RuntimeError("Paper position size resolved to zero")

        actual_risk = stop_distance * quantity
        actual_notional = abs(entry * quantity)

        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup=scenario.name,
            side=side,
            stage="ORDER_INTENT",
            outcome="READY",
            candidate=True,
            selected=True,
            score=1.0,
            entry_reference=entry,
            stop_reference=stop,
            target_reference=take,
            quantity=quantity,
            planned_risk_usdt=actual_risk,
            planned_notional_usdt=actual_notional,
            reason_codes=reason_codes,
            evidence={
                "source": "DETERMINISTIC_PAPER_SCENARIO",
                "risk_budget_usdt": risk_budget,
                "max_notional_usdt": max_notional,
                "leverage": leverage,
                "reward_risk": 1.8,
            },
            risk_code="OK",
            risk_message="ok",
        )

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
        db.refresh(trade)

        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=decision_id,
            symbol=symbol,
            setup=scenario.name,
            side=side,
            stage="FILL",
            outcome="FILLED",
            candidate=True,
            selected=True,
            score=1.0,
            entry_reference=entry,
            stop_reference=stop,
            target_reference=take,
            quantity=quantity,
            planned_risk_usdt=actual_risk,
            planned_notional_usdt=actual_notional,
            reason_codes=reason_codes,
            evidence={
                "source": "LOCAL_PAPER",
                "fill_price": entry,
                "leverage": leverage,
                "fee_estimate_usdt": abs(entry * quantity) * 0.0004,
            },
            risk_code="OK",
            risk_message="ok",
            trade_id=trade.id,
        )

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
            "actual_risk_usdt": actual_risk,
            "actual_risk_pct_equity": (actual_risk / equity * 100.0) if equity > 0 else 0.0,
            "max_notional_usdt": max_notional,
            "actual_notional_usdt": actual_notional,
            "daily_pnl_usdt": daily_pnl,
            "trades_today": trades_today,
            "reason_codes": reason_codes,
            "cycle_id": cycle_id,
            "decision_id": decision_id,
        }


ENGINE = TradingEngine()
