from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func

from config import DEFAULT_CONFIG, INITIAL_TRADING_UNIVERSE, REFERENCE_CAPITAL_USDT
from models.account_snapshot import AccountSnapshot
from models.config_model import ConfigModel
from models.paper_order_intent import PaperOrderIntent
from models.position import Position
from models.risk_event import RiskEvent
from models.runtime_state import RuntimeState
from models.signal import Signal
from models.trade import Trade
from risk.risk_manager import RiskContext, RiskManager
from services.account_service import latest_account, realized_pnl_for_utc_day, trades_opened_on_utc_day
from services.market_data_service import BinanceDemoClosedCandleProvider
from services.runtime_supervisor import RUNTIME_STATE_ID, RuntimeSupervisor
from services.seven_symbol_coordinator import SevenSymbolScanCoordinator
from services.strategy_runtime import DEFAULT_REWARD_RISK, JiangheV1ClosedCandleEvaluator
from services.trade_audit_service import add_trade_decision, decision_id_for_trade, decode_json_field

PAPER_FEE_RATE = 0.0004
PAPER_SLIPPAGE_BPS = 2.0
MAX_HOLD_BARS = 64
PENDING_INTENT_MAX_AGE_MINUTES = 3


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _apply_slippage(price: float, side: str, *, is_entry: bool) -> float:
    rate = PAPER_SLIPPAGE_BPS / 10_000.0
    if side == "LONG":
        return float(price) * (1.0 + rate if is_entry else 1.0 - rate)
    return float(price) * (1.0 - rate if is_entry else 1.0 + rate)


def _ensure_config(db) -> ConfigModel:
    row = db.query(ConfigModel).first()
    fixed = ",".join(INITIAL_TRADING_UNIVERSE)
    if row is None:
        values = DEFAULT_CONFIG.model_dump()
        row = ConfigModel(**{**values, "enabled_symbols": fixed})
        db.add(row)
        db.commit()
        db.refresh(row)
    elif row.enabled_symbols != fixed:
        row.enabled_symbols = fixed
        db.commit()
    return row


def _config_dict(cfg: ConfigModel) -> dict:
    return {
        "dry_run": bool(cfg.dry_run),
        "testnet": bool(cfg.testnet),
        "margin_mode": cfg.margin_mode,
        "default_leverage": int(cfg.default_leverage),
        "max_leverage": int(cfg.max_leverage),
        "risk_per_trade": float(cfg.risk_per_trade),
        "max_margin_per_trade": float(cfg.max_margin_per_trade),
        "max_daily_loss": float(cfg.max_daily_loss),
        "max_trades_per_day": int(cfg.max_trades_per_day),
        "max_open_positions": int(cfg.max_open_positions),
        "max_consecutive_losses": int(cfg.max_consecutive_losses),
        "enabled_symbols": list(INITIAL_TRADING_UNIVERSE),
    }


def _consecutive_losses(db) -> int:
    rows = (
        db.query(Trade)
        .filter(Trade.close_time.isnot(None))
        .order_by(desc(Trade.id))
        .limit(20)
        .all()
    )
    count = 0
    for row in rows:
        if float(row.pnl or 0.0) < 0:
            count += 1
        else:
            break
    return count


def _risk_context(db) -> tuple[dict, RiskContext, ConfigModel]:
    cfg = _ensure_config(db)
    cfg_dict = _config_dict(cfg)
    account = latest_account(db)
    daily_pnl = realized_pnl_for_utc_day(db)
    equity = float(account["equity"])
    return (
        cfg_dict,
        RiskContext(
            equity=equity,
            daily_pnl=daily_pnl,
            trades_today=trades_opened_on_utc_day(db),
            open_positions=db.query(Position).filter(Position.is_open.is_(True)).count(),
            consecutive_losses=_consecutive_losses(db),
            day_start_equity=max(0.0, equity - daily_pnl),
        ),
        cfg,
    )


class AutonomousPaperRuntime:
    """Seven-symbol autonomous Paper worker; never sends exchange orders.

    Cycle order is deliberately deterministic:
      1. renew single-worker lease and validate ledger;
      2. wait for one new fully-closed 1m candle;
      3. manage an existing Paper position, else fill one persisted next-bar
         intent, else scan all seven symbols and persist at most one new intent;
      4. checkpoint the processed candle and heartbeat.

    The runtime uses Binance Demo public market data only. It has no private
    exchange credentials and no create/cancel/close exchange-order methods.
    """

    def __init__(
        self,
        *,
        provider: BinanceDemoClosedCandleProvider | None = None,
        evaluator: JiangheV1ClosedCandleEvaluator | None = None,
        coordinator: SevenSymbolScanCoordinator | None = None,
        supervisor: RuntimeSupervisor | None = None,
    ) -> None:
        self.provider = provider or BinanceDemoClosedCandleProvider()
        self.evaluator = evaluator or JiangheV1ClosedCandleEvaluator(self.provider)
        self.coordinator = coordinator or SevenSymbolScanCoordinator()
        self.supervisor = supervisor or RuntimeSupervisor()
        self.risk = RiskManager()

    def _latest_reference_close(self):
        bars = self.provider.fetch_closed_ohlcv(INITIAL_TRADING_UNIVERSE[0], "1m", limit=3)
        if bars.empty:
            raise RuntimeError("NO_CLOSED_REFERENCE_1M_CANDLE")
        return bars["timestamp"].iloc[-1].to_pydatetime()

    def _checkpoint(self, db, close_time: datetime, cycle_id: str = "") -> None:
        row = self.supervisor.ensure_state(db)
        row.last_execution_close_at = _utc(close_time)
        if cycle_id:
            row.last_cycle_id = cycle_id
        row.last_error = ""
        db.commit()

    def _is_new_reference_candle(self, db, close_time: datetime) -> bool:
        row = self.supervisor.ensure_state(db)
        previous = _utc(row.last_execution_close_at)
        current = _utc(close_time)
        return previous is None or (current is not None and current > previous)

    def _audit_risk(self, db, item, *, cycle_id: str, allowed: bool, code: str, message: str) -> None:
        intent = item.intent
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=item.decision_id,
            symbol=intent.symbol,
            setup=intent.setup,
            side=intent.side,
            stage="RISK",
            outcome="PASSED" if allowed else "BLOCKED",
            candidate=True,
            selected=True,
            score=float(intent.score),
            entry_reference=float(intent.entry_reference),
            stop_reference=float(intent.stop_reference),
            target_reference=intent.target_reference,
            reason_codes=list(intent.reason_codes),
            evidence=intent.evidence,
            risk_code=code,
            risk_message=message,
        )

    def _stage_pending_intent(self, db, selected, cycle_id: str, reference_close: datetime) -> dict:
        cfg_dict, ctx, cfg = _risk_context(db)
        if not cfg_dict["dry_run"]:
            raise RuntimeError("AUTONOMOUS_PAPER_REQUIRES_DRY_RUN")
        leverage = int(cfg.default_leverage)
        risk_decision = self.risk.evaluate(
            cfg_dict,
            ctx,
            selected.intent.symbol,
            rr=DEFAULT_REWARD_RISK,
            leverage=leverage,
            margin_ratio=min(0.05, float(cfg.max_margin_per_trade)),
        )
        self._audit_risk(
            db,
            selected,
            cycle_id=cycle_id,
            allowed=risk_decision.allowed,
            code=risk_decision.code,
            message=risk_decision.message,
        )
        if not risk_decision.allowed:
            db.add(
                RiskEvent(
                    rule="autonomous_paper_pretrade",
                    symbol=selected.intent.symbol,
                    action="blocked",
                    reason=f"{risk_decision.code}:{risk_decision.message}",
                )
            )
            db.commit()
            return {
                "action": "RISK_BLOCKED",
                "symbol": selected.intent.symbol,
                "reason_code": risk_decision.code,
                "decision_id": selected.decision_id,
                "cycle_id": cycle_id,
            }

        evidence = dict(selected.intent.evidence)
        candidate_close = evidence.get("latest_closed_1m")
        if candidate_close:
            parsed = datetime.fromisoformat(str(candidate_close).replace("Z", "+00:00"))
            if _utc(parsed) != _utc(reference_close):
                add_trade_decision(
                    db,
                    cycle_id=cycle_id,
                    decision_id=selected.decision_id,
                    symbol=selected.intent.symbol,
                    setup=selected.intent.setup,
                    side=selected.intent.side,
                    stage="ORDER_INTENT",
                    outcome="CANCELLED_STALE_SIGNAL",
                    candidate=True,
                    selected=True,
                    score=float(selected.intent.score),
                    entry_reference=float(selected.intent.entry_reference),
                    stop_reference=float(selected.intent.stop_reference),
                    target_reference=selected.intent.target_reference,
                    reason_codes=list(selected.intent.reason_codes) + ["STALE_SIGNAL_CANDLE"],
                    evidence=evidence,
                    risk_code="STALE_SIGNAL_CANDLE",
                    risk_message="candidate did not use the current closed 1m candle",
                )
                return {"action": "STALE_SIGNAL_CANCELLED", "decision_id": selected.decision_id}

        pending = PaperOrderIntent(
            decision_id=selected.decision_id,
            cycle_id=cycle_id,
            symbol=selected.intent.symbol,
            setup=selected.intent.setup,
            side=selected.intent.side,
            score=float(selected.intent.score),
            signal_close_time=_utc(reference_close),
            stop_reference=float(selected.intent.stop_reference),
            reward_risk=DEFAULT_REWARD_RISK,
            status="PENDING",
            reason_codes_json=json.dumps(list(selected.intent.reason_codes), ensure_ascii=False),
            evidence_json=json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str),
        )
        db.add(pending)
        db.commit()
        add_trade_decision(
            db,
            cycle_id=cycle_id,
            decision_id=selected.decision_id,
            symbol=selected.intent.symbol,
            setup=selected.intent.setup,
            side=selected.intent.side,
            stage="ORDER_INTENT",
            outcome="PENDING_NEXT_BAR",
            candidate=True,
            selected=True,
            score=float(selected.intent.score),
            entry_reference=float(selected.intent.entry_reference),
            stop_reference=float(selected.intent.stop_reference),
            target_reference=selected.intent.target_reference,
            reason_codes=list(selected.intent.reason_codes),
            evidence={**evidence, "paper_fill_policy": "NEXT_CLOSED_1M_BAR_OPEN"},
            risk_code="OK",
            risk_message="pretrade risk passed; awaiting next bar open",
        )
        return {
            "action": "PENDING_NEXT_BAR",
            "symbol": selected.intent.symbol,
            "decision_id": selected.decision_id,
            "cycle_id": cycle_id,
        }

    def _cancel_pending(self, db, pending: PaperOrderIntent, code: str, message: str) -> dict:
        pending.status = "CANCELLED"
        pending.cancelled_at = datetime.now(timezone.utc)
        pending.cancel_reason = code
        db.commit()
        add_trade_decision(
            db,
            cycle_id=pending.cycle_id,
            decision_id=pending.decision_id,
            symbol=pending.symbol,
            setup=pending.setup,
            side=pending.side,
            stage="ORDER_INTENT",
            outcome="CANCELLED",
            candidate=True,
            selected=True,
            score=float(pending.score),
            stop_reference=float(pending.stop_reference),
            reason_codes=decode_json_field(pending.reason_codes_json, []) + [code],
            evidence=decode_json_field(pending.evidence_json, {}),
            risk_code=code,
            risk_message=message,
        )
        return {"action": "PENDING_CANCELLED", "reason_code": code, "decision_id": pending.decision_id}

    def _fill_pending(self, db, pending: PaperOrderIntent) -> dict:
        signal_close = _utc(pending.signal_close_time)
        if signal_close is None:
            return self._cancel_pending(db, pending, "INVALID_SIGNAL_TIME", "missing signal close time")

        bars = self.provider.fetch_closed_ohlcv(pending.symbol, "1m", limit=10)
        if bars.empty:
            return {"action": "WAITING_NEXT_BAR", "decision_id": pending.decision_id}
        eligible = bars[bars["open_time"] >= signal_close]
        if eligible.empty:
            if datetime.now(timezone.utc) > signal_close + timedelta(minutes=PENDING_INTENT_MAX_AGE_MINUTES):
                return self._cancel_pending(db, pending, "NEXT_BAR_TIMEOUT", "next closed 1m bar did not arrive in time")
            return {"action": "WAITING_NEXT_BAR", "decision_id": pending.decision_id}

        fill_bar = eligible.iloc[0]
        fill_open_time = fill_bar["open_time"].to_pydatetime()
        if _utc(fill_open_time) != signal_close:
            return self._cancel_pending(db, pending, "NEXT_BAR_DATA_GAP", "expected next 1m bar is missing")

        side = str(pending.side).upper()
        raw_entry = float(fill_bar["open"])
        entry = _apply_slippage(raw_entry, side, is_entry=True)
        stop = float(pending.stop_reference)
        stop_distance = entry - stop if side == "LONG" else stop - entry
        if stop_distance <= 0:
            return self._cancel_pending(db, pending, "ENTRY_GAPPED_THROUGH_STOP", "next-bar entry invalidated the structural stop")

        cfg_dict, ctx, cfg = _risk_context(db)
        leverage = int(cfg.default_leverage)
        risk_decision = self.risk.evaluate(
            cfg_dict,
            ctx,
            pending.symbol,
            rr=float(pending.reward_risk),
            leverage=leverage,
            margin_ratio=min(0.05, float(cfg.max_margin_per_trade)),
        )
        if not risk_decision.allowed:
            return self._cancel_pending(db, pending, risk_decision.code, risk_decision.message)

        risk_budget = self.risk.risk_budget_usdt(cfg_dict, ctx.equity)
        qty_by_stop = risk_budget / stop_distance
        max_notional = float(ctx.equity) * float(cfg.max_margin_per_trade) * leverage
        qty_by_notional = max_notional / max(entry, 1e-12)
        quantity = min(qty_by_stop, qty_by_notional)
        if quantity <= 0:
            return self._cancel_pending(db, pending, "ZERO_POSITION_SIZE", "position size resolved to zero")

        direction = 1.0 if side == "LONG" else -1.0
        target = entry + direction * float(pending.reward_risk) * stop_distance
        actual_risk = stop_distance * quantity
        actual_notional = abs(entry * quantity)
        reasons = decode_json_field(pending.reason_codes_json, [])
        evidence = decode_json_field(pending.evidence_json, {})

        trade = Trade(
            symbol=pending.symbol,
            side=side,
            open_time=_utc(fill_open_time),
            close_time=None,
            entry_price=entry,
            exit_price=0.0,
            stop_loss=stop,
            take_profit=target,
            quantity=quantity,
            leverage=leverage,
            fee=actual_notional * PAPER_FEE_RATE,
            pnl=0.0,
            dry_run=True,
            reason=f"{pending.setup};" + ",".join(reasons),
            deepseek_summary="AUTONOMOUS_PAPER_NO_LLM",
        )
        db.add(trade)
        db.add(
            Position(
                symbol=pending.symbol,
                side=side,
                entry_price=entry,
                mark_price=entry,
                quantity=quantity,
                leverage=leverage,
                unrealized_pnl=0.0,
                is_open=True,
            )
        )
        db.add(
            Signal(
                symbol=pending.symbol,
                timeframe="1m_NEXT_OPEN",
                signal_type=side,
                score=float(pending.score),
                details=f"{pending.setup}; decision_id={pending.decision_id}",
            )
        )
        pending.status = "FILLED"
        pending.filled_at = _utc(fill_open_time)
        db.commit()
        db.refresh(trade)

        add_trade_decision(
            db,
            cycle_id=pending.cycle_id,
            decision_id=pending.decision_id,
            symbol=pending.symbol,
            setup=pending.setup,
            side=side,
            stage="FILL",
            outcome="FILLED",
            candidate=True,
            selected=True,
            score=float(pending.score),
            entry_reference=entry,
            stop_reference=stop,
            target_reference=target,
            quantity=quantity,
            planned_risk_usdt=actual_risk,
            planned_notional_usdt=actual_notional,
            reason_codes=reasons,
            evidence={
                **evidence,
                "raw_next_bar_open": raw_entry,
                "paper_entry_after_slippage": entry,
                "slippage_bps": PAPER_SLIPPAGE_BPS,
                "risk_budget_usdt": risk_budget,
                "actual_risk_usdt": actual_risk,
                "actual_notional_usdt": actual_notional,
            },
            risk_code="OK",
            risk_message="paper fill",
            trade_id=trade.id,
        )

        # The next bar is already fully closed when Paper fills it. Replaying
        # that same bar immediately preserves backtest semantics if stop/target
        # was touched after the open.
        exit_result = self._process_open_position(db, preloaded_bars=bars)
        if exit_result.get("action") == "CLOSE_PAPER_POSITION":
            return {"action": "FILL_AND_EXIT", "fill_trade_id": trade.id, "exit": exit_result}
        return {
            "action": "FILL_PAPER_POSITION",
            "symbol": pending.symbol,
            "trade_id": trade.id,
            "decision_id": pending.decision_id,
            "entry": entry,
            "stop": stop,
            "target": target,
            "quantity": quantity,
            "planned_risk_usdt": actual_risk,
            "planned_notional_usdt": actual_notional,
        }

    def _process_open_position(self, db, *, preloaded_bars=None) -> dict:
        position = db.query(Position).filter(Position.is_open.is_(True)).order_by(desc(Position.id)).first()
        trade = db.query(Trade).filter(Trade.close_time.is_(None)).order_by(desc(Trade.id)).first()
        if position is None or trade is None:
            return {"action": "NO_OPEN_POSITION"}

        bars = preloaded_bars
        if bars is None:
            bars = self.provider.fetch_closed_ohlcv(trade.symbol, "1m", limit=200)
        opened = _utc(trade.open_time)
        if opened is None or bars.empty:
            return {"action": "WAITING_POSITION_BAR", "symbol": trade.symbol}
        active = bars[bars["open_time"] >= opened].head(MAX_HOLD_BARS)
        if active.empty:
            return {"action": "WAITING_POSITION_BAR", "symbol": trade.symbol}

        side = str(trade.side).upper()
        stop = float(trade.stop_loss)
        target = float(trade.take_profit)
        raw_exit = None
        exit_reason = None
        exit_time = None

        for _, bar in active.iterrows():
            open_i = float(bar["open"])
            high = float(bar["high"])
            low = float(bar["low"])
            if side == "LONG" and open_i <= stop:
                raw_exit, exit_reason = open_i, "STOP_GAP"
            elif side == "SHORT" and open_i >= stop:
                raw_exit, exit_reason = open_i, "STOP_GAP"
            else:
                hit_stop = low <= stop if side == "LONG" else high >= stop
                hit_target = high >= target if side == "LONG" else low <= target
                if hit_stop and hit_target:
                    raw_exit, exit_reason = stop, "STOP"
                elif hit_stop:
                    raw_exit, exit_reason = stop, "STOP"
                elif hit_target:
                    raw_exit, exit_reason = target, "TARGET"
            if exit_reason:
                exit_time = bar["timestamp"].to_pydatetime()
                break

        if exit_reason is None and len(active) >= MAX_HOLD_BARS:
            bar = active.iloc[MAX_HOLD_BARS - 1]
            raw_exit = float(bar["close"])
            exit_reason = "TIME"
            exit_time = bar["timestamp"].to_pydatetime()

        latest_bar = active.iloc[-1]
        if exit_reason is None or raw_exit is None or exit_time is None:
            mark = float(latest_bar["close"])
            direction = 1.0 if side == "LONG" else -1.0
            position.mark_price = mark
            position.unrealized_pnl = direction * (mark - float(trade.entry_price)) * float(trade.quantity)
            db.commit()
            return {
                "action": "MARK_OPEN_POSITION",
                "symbol": trade.symbol,
                "mark_price": mark,
                "unrealized_pnl": float(position.unrealized_pnl),
            }

        exit_price = _apply_slippage(float(raw_exit), side, is_entry=False)
        entry = float(trade.entry_price)
        qty = float(trade.quantity)
        direction = 1.0 if side == "LONG" else -1.0
        gross = direction * (exit_price - entry) * qty
        fees = (abs(entry * qty) + abs(exit_price * qty)) * PAPER_FEE_RATE
        net = gross - fees

        trade.exit_price = exit_price
        trade.fee = fees
        trade.pnl = net
        trade.close_time = _utc(exit_time)
        position.mark_price = exit_price
        position.unrealized_pnl = 0.0
        position.is_open = False

        previous = latest_account(db)
        balance = float(previous["balance"]) + net
        total_pnl = float(previous["total_pnl"]) + net
        exit_day = _utc(exit_time).date()
        daily_pnl = realized_pnl_for_utc_day(db, exit_day) + net
        peak = max(
            REFERENCE_CAPITAL_USDT,
            float(db.query(func.max(AccountSnapshot.equity)).scalar() or 0.0),
        )
        drawdown = max(0.0, (peak - balance) / peak) if peak > 0 else 0.0
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
                cycle_id=f"exit-{trade.id}",
                decision_id=decision_id,
                symbol=trade.symbol,
                setup="AUTONOMOUS_PAPER_EXIT",
                side=side,
                stage="EXIT",
                outcome="CLOSED",
                candidate=True,
                selected=True,
                entry_reference=entry,
                stop_reference=stop,
                target_reference=target,
                quantity=qty,
                planned_notional_usdt=abs(entry * qty),
                reason_codes=[exit_reason],
                evidence={
                    "raw_exit": raw_exit,
                    "paper_exit_after_slippage": exit_price,
                    "gross_pnl_usdt": gross,
                    "fees_usdt": fees,
                    "net_pnl_usdt": net,
                    "same_bar_policy": "STOP_FIRST",
                    "max_hold_bars": MAX_HOLD_BARS,
                },
                risk_code="OK",
                risk_message="paper position closed",
                trade_id=trade.id,
            )

        return {
            "action": "CLOSE_PAPER_POSITION",
            "symbol": trade.symbol,
            "trade_id": trade.id,
            "decision_id": decision_id,
            "exit_reason": exit_reason,
            "exit_price": exit_price,
            "net_pnl_usdt": net,
            "balance_usdt": balance,
        }

    async def cycle_once(self, db, *, owner: str) -> dict:
        lease = self.supervisor.heartbeat(db, owner, ttl_seconds=90)
        if not lease.allowed:
            return {"action": "RUNTIME_BLOCKED", "reason_code": lease.code, "reason": lease.message}

        ledger = self.supervisor.validate_local_ledger(db)
        if not ledger.ok:
            return {"action": "KILL_SWITCH_LEDGER_INVALID", "ledger": ledger.to_dict()}

        reference_close = self._latest_reference_close()
        if not self._is_new_reference_candle(db, reference_close):
            return {"action": "NO_NEW_CLOSED_CANDLE", "closed_1m": reference_close}

        if ledger.open_positions == 1:
            result = self._process_open_position(db)
            self._checkpoint(db, reference_close)
            return result

        pending = (
            db.query(PaperOrderIntent)
            .filter(PaperOrderIntent.status == "PENDING")
            .order_by(PaperOrderIntent.id)
            .first()
        )
        if pending is not None:
            result = self._fill_pending(db, pending)
            self._checkpoint(db, reference_close, pending.cycle_id)
            return result

        scan = await self.coordinator.scan_once(db, self.evaluator.evaluate_symbol)
        if scan.selected is None:
            self._checkpoint(db, reference_close, scan.cycle_id)
            return {
                "action": "NO_CANDIDATE",
                "cycle_id": scan.cycle_id,
                "scanned_symbols": list(scan.scanned_symbols),
            }

        result = self._stage_pending_intent(db, scan.selected, scan.cycle_id, reference_close)
        self._checkpoint(db, reference_close, scan.cycle_id)
        return result

    async def run_forever(
        self,
        *,
        db_factory,
        stop_event: asyncio.Event,
        owner: str | None = None,
        close_delay_seconds: float = 2.0,
    ) -> None:
        """Run one cycle shortly after every UTC minute boundary.

        Nothing auto-starts this method. RuntimeState starts with kill_switch=ON,
        and a dedicated worker must explicitly acquire the PAPER lease first.
        """

        owner_id = owner or f"paper-{uuid.uuid4().hex}"
        db = db_factory()
        try:
            lease = self.supervisor.acquire_lease(db, owner_id, ttl_seconds=90, mode="PAPER")
            if not lease.allowed:
                raise RuntimeError(f"{lease.code}:{lease.message}")
        finally:
            db.close()

        try:
            while not stop_event.is_set():
                now = time.time()
                wait = max(0.0, 60.0 - (now % 60.0) + close_delay_seconds)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=wait)
                    break
                except asyncio.TimeoutError:
                    pass

                db = db_factory()
                try:
                    result = await self.cycle_once(db, owner=owner_id)
                    if result.get("action") in {"RUNTIME_BLOCKED", "KILL_SWITCH_LEDGER_INVALID"}:
                        break
                except Exception as exc:
                    self.supervisor.record_fatal_error(db, f"AUTONOMOUS_PAPER_RUNTIME:{type(exc).__name__}:{exc}")
                    break
                finally:
                    db.close()
        finally:
            db = db_factory()
            try:
                self.supervisor.release_lease(db, owner_id)
            finally:
                db.close()
