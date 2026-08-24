from __future__ import annotations

from dataclasses import asdict, dataclass

from models.position import Position
from models.trade import Trade


def _canonical_symbol(value: str | None) -> str:
    text = str(value or "").upper().strip()
    if ":" in text:
        text = text.split(":", 1)[0]
    return text


def _canonical_side(value: str | None) -> str:
    text = str(value or "").upper().strip()
    if text in {"BUY", "LONG"}:
        return "LONG"
    if text in {"SELL", "SHORT"}:
        return "SHORT"
    return text


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    errors: tuple[str, ...]
    local_open_positions: int
    local_open_trades: int
    exchange_open_positions: int
    exchange_open_orders: int
    local_position: dict | None
    exchange_position: dict | None

    def to_dict(self) -> dict:
        return asdict(self)


def reconcile_local_with_demo(db, snapshot: dict, *, quantity_tolerance: float = 1e-9) -> ReconciliationResult:
    """Compare local execution ledger with a read-only Binance Demo snapshot.

    Never auto-heal an ambiguous state. Because S7 has no persistent live
    exchange-order state machine yet, any open Binance Demo order is considered
    unreconciled and blocks readiness.
    """
    if quantity_tolerance < 0:
        raise ValueError("quantity_tolerance must be >= 0")

    local_positions = db.query(Position).filter(Position.is_open.is_(True)).order_by(Position.id).all()
    local_trades = db.query(Trade).filter(Trade.close_time.is_(None)).order_by(Trade.id).all()
    exchange_positions = list(snapshot.get("positions") or [])
    exchange_orders = list(snapshot.get("open_orders") or [])

    errors: list[str] = []
    if len(local_positions) > 1:
        errors.append("LOCAL_MORE_THAN_ONE_OPEN_POSITION")
    if len(local_trades) > 1:
        errors.append("LOCAL_MORE_THAN_ONE_OPEN_TRADE")
    if len(exchange_positions) > 1:
        errors.append("DEMO_MORE_THAN_ONE_OPEN_POSITION")
    if len(local_positions) != len(local_trades):
        errors.append("LOCAL_POSITION_TRADE_COUNT_MISMATCH")
    if len(local_positions) != len(exchange_positions):
        errors.append("LOCAL_DEMO_POSITION_COUNT_MISMATCH")
    if exchange_orders:
        errors.append("UNRECONCILED_DEMO_OPEN_ORDERS")

    local_view = None
    exchange_view = None
    if local_positions:
        p = local_positions[0]
        local_view = {
            "symbol": _canonical_symbol(p.symbol),
            "side": _canonical_side(p.side),
            "quantity": float(p.quantity or 0.0),
            "entry_price": float(p.entry_price or 0.0),
        }
    if exchange_positions:
        p = exchange_positions[0]
        exchange_view = {
            "symbol": _canonical_symbol(p.get("symbol")),
            "side": _canonical_side(p.get("side")),
            "quantity": abs(float(p.get("contracts") or 0.0)),
            "entry_price": float(p.get("entry_price") or 0.0),
            "leverage": float(p.get("leverage") or 0.0),
            "margin_mode": str(p.get("margin_mode") or "").lower(),
        }

    if local_view and exchange_view:
        if local_view["symbol"] != exchange_view["symbol"]:
            errors.append("LOCAL_DEMO_POSITION_SYMBOL_MISMATCH")
        if local_view["side"] != exchange_view["side"]:
            errors.append("LOCAL_DEMO_POSITION_SIDE_MISMATCH")
        local_qty = float(local_view["quantity"])
        exchange_qty = float(exchange_view["quantity"])
        tolerance = max(float(quantity_tolerance), max(local_qty, exchange_qty) * 1e-8)
        if abs(local_qty - exchange_qty) > tolerance:
            errors.append("LOCAL_DEMO_POSITION_QUANTITY_MISMATCH")

    if local_positions and local_trades:
        p = local_positions[0]
        t = local_trades[0]
        if _canonical_symbol(p.symbol) != _canonical_symbol(t.symbol):
            errors.append("LOCAL_POSITION_TRADE_SYMBOL_MISMATCH")
        if _canonical_side(p.side) != _canonical_side(t.side):
            errors.append("LOCAL_POSITION_TRADE_SIDE_MISMATCH")
        local_p_qty = abs(float(p.quantity or 0.0))
        local_t_qty = abs(float(t.quantity or 0.0))
        tolerance = max(float(quantity_tolerance), max(local_p_qty, local_t_qty) * 1e-8)
        if abs(local_p_qty - local_t_qty) > tolerance:
            errors.append("LOCAL_POSITION_TRADE_QUANTITY_MISMATCH")

    return ReconciliationResult(
        ok=not errors,
        errors=tuple(dict.fromkeys(errors)),
        local_open_positions=len(local_positions),
        local_open_trades=len(local_trades),
        exchange_open_positions=len(exchange_positions),
        exchange_open_orders=len(exchange_orders),
        local_position=local_view,
        exchange_position=exchange_view,
    )
