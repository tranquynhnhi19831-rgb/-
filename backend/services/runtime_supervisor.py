from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from models.paper_order_intent import PaperOrderIntent
from models.position import Position
from models.risk_event import RiskEvent
from models.runtime_state import RuntimeState
from models.trade import Trade
from services.log_service import add_log

RUNTIME_STATE_ID = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class LeaseDecision:
    allowed: bool
    code: str
    message: str


@dataclass(frozen=True)
class LedgerCheck:
    ok: bool
    errors: tuple[str, ...]
    open_positions: int
    open_trades: int
    pending_intents: int

    def to_dict(self) -> dict:
        return asdict(self)


class RuntimeSupervisor:
    """Fail-closed control plane for one autonomous worker.

    It provides a short DB-backed lease, heartbeat, kill switch and a minimal
    local-ledger reconciliation check. The runtime never auto-heals ambiguous
    trading state. If Trade/Position/PendingIntent semantics disagree, it
    engages the kill switch and requires explicit operator review.
    """

    @staticmethod
    def ensure_state(db) -> RuntimeState:
        row = db.query(RuntimeState).filter(RuntimeState.id == RUNTIME_STATE_ID).first()
        if row is None:
            row = RuntimeState(id=RUNTIME_STATE_ID, mode="PAPER", kill_switch=True)
            db.add(row)
            db.commit()
            db.refresh(row)
        return row

    def status(self, db) -> dict:
        row = self.ensure_state(db)
        now = _utcnow()
        expiry = _as_utc(row.lease_expires_at)
        return {
            "mode": row.mode,
            "kill_switch": bool(row.kill_switch),
            "lease_owner": row.lease_owner,
            "lease_active": bool(row.lease_owner and expiry and expiry > now),
            "lease_expires_at": row.lease_expires_at,
            "heartbeat_at": row.heartbeat_at,
            "last_cycle_id": row.last_cycle_id,
            "last_execution_close_at": row.last_execution_close_at,
            "last_error": row.last_error,
        }

    def set_kill_switch(self, db, enabled: bool, *, reason: str = "") -> dict:
        row = self.ensure_state(db)
        row.kill_switch = bool(enabled)
        if enabled and reason:
            row.last_error = reason
        if not enabled:
            row.last_error = ""
        db.commit()
        add_log(
            db,
            f"RUNTIME kill_switch={'ON' if enabled else 'OFF'} reason={reason or '-'}",
            "WARNING" if enabled else "INFO",
            "runtime",
        )
        return self.status(db)

    def acquire_lease(
        self,
        db,
        owner: str,
        *,
        ttl_seconds: int = 90,
        mode: str = "PAPER",
    ) -> LeaseDecision:
        owner = owner.strip()
        if not owner:
            return LeaseDecision(False, "INVALID_OWNER", "runtime owner id is required")
        if ttl_seconds < 15:
            return LeaseDecision(False, "INVALID_TTL", "runtime lease ttl must be >= 15 seconds")
        if mode != "PAPER":
            return LeaseDecision(False, "MODE_NOT_ALLOWED", "S7 autonomous runtime supports PAPER only")

        row = self.ensure_state(db)
        if row.kill_switch:
            return LeaseDecision(False, "KILL_SWITCH_ENGAGED", "runtime kill switch is engaged")

        now = _utcnow()
        expiry = _as_utc(row.lease_expires_at)
        if row.lease_owner and row.lease_owner != owner and expiry and expiry > now:
            return LeaseDecision(False, "LEASE_HELD", f"runtime lease is held by {row.lease_owner}")

        row.mode = mode
        row.lease_owner = owner
        row.heartbeat_at = now
        row.lease_expires_at = now + timedelta(seconds=ttl_seconds)
        db.commit()
        return LeaseDecision(True, "OK", "runtime lease acquired")

    def heartbeat(
        self,
        db,
        owner: str,
        *,
        ttl_seconds: int = 90,
        cycle_id: str = "",
    ) -> LeaseDecision:
        row = self.ensure_state(db)
        now = _utcnow()
        expiry = _as_utc(row.lease_expires_at)
        if row.kill_switch:
            return LeaseDecision(False, "KILL_SWITCH_ENGAGED", "runtime kill switch is engaged")
        if row.lease_owner != owner:
            return LeaseDecision(False, "LEASE_OWNER_MISMATCH", "runtime lease owner mismatch")
        if expiry is not None and expiry <= now:
            return LeaseDecision(False, "LEASE_EXPIRED", "runtime lease expired")

        row.heartbeat_at = now
        row.lease_expires_at = now + timedelta(seconds=ttl_seconds)
        if cycle_id:
            row.last_cycle_id = cycle_id
        db.commit()
        return LeaseDecision(True, "OK", "runtime heartbeat renewed")

    def release_lease(self, db, owner: str) -> LeaseDecision:
        row = self.ensure_state(db)
        if row.lease_owner and row.lease_owner != owner:
            return LeaseDecision(False, "LEASE_OWNER_MISMATCH", "cannot release another worker's lease")
        row.lease_owner = ""
        row.lease_expires_at = None
        db.commit()
        return LeaseDecision(True, "OK", "runtime lease released")

    def record_fatal_error(self, db, message: str) -> None:
        row = self.ensure_state(db)
        row.kill_switch = True
        row.last_error = str(message)
        db.add(
            RiskEvent(
                rule="runtime_supervisor",
                symbol="",
                action="kill_switch",
                reason=str(message),
            )
        )
        db.commit()
        add_log(db, f"RUNTIME FATAL: {message}", "ERROR", "runtime")

    def validate_local_ledger(self, db) -> LedgerCheck:
        positions = (
            db.query(Position)
            .filter(Position.is_open.is_(True))
            .order_by(Position.id)
            .all()
        )
        trades = (
            db.query(Trade)
            .filter(Trade.close_time.is_(None))
            .order_by(Trade.id)
            .all()
        )
        pending = (
            db.query(PaperOrderIntent)
            .filter(PaperOrderIntent.status == "PENDING")
            .order_by(PaperOrderIntent.id)
            .all()
        )

        errors: list[str] = []
        if len(positions) > 1:
            errors.append("MORE_THAN_ONE_OPEN_POSITION")
        if len(trades) > 1:
            errors.append("MORE_THAN_ONE_OPEN_TRADE")
        if len(pending) > 1:
            errors.append("MORE_THAN_ONE_PENDING_PAPER_INTENT")
        if len(positions) != len(trades):
            errors.append("OPEN_POSITION_TRADE_COUNT_MISMATCH")
        if positions and trades:
            p, t = positions[0], trades[0]
            if p.symbol != t.symbol:
                errors.append("OPEN_POSITION_TRADE_SYMBOL_MISMATCH")
            if str(p.side).upper() != str(t.side).upper():
                errors.append("OPEN_POSITION_TRADE_SIDE_MISMATCH")
            if abs(float(p.quantity or 0.0) - float(t.quantity or 0.0)) > 1e-12:
                errors.append("OPEN_POSITION_TRADE_QUANTITY_MISMATCH")
        if positions and pending:
            errors.append("OPEN_POSITION_AND_PENDING_INTENT")

        result = LedgerCheck(
            ok=not errors,
            errors=tuple(errors),
            open_positions=len(positions),
            open_trades=len(trades),
            pending_intents=len(pending),
        )
        if errors:
            self.record_fatal_error(db, "LOCAL_LEDGER_INVALID:" + ",".join(errors))
        return result


SUPERVISOR = RuntimeSupervisor()
