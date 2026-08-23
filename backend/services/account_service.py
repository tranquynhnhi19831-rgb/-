from datetime import date, datetime, timezone

from sqlalchemy import desc, func

from config import REFERENCE_CAPITAL_USDT
from models.account_snapshot import AccountSnapshot
from models.trade import Trade


def max_drawdown_from_equities(equities: list[float], reference_capital: float = REFERENCE_CAPITAL_USDT) -> float:
    peak = max(float(reference_capital), 0.0)
    max_drawdown = 0.0
    for raw_equity in equities:
        equity = float(raw_equity)
        if equity > peak:
            peak = equity
            continue
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)
    return max(0.0, max_drawdown)


def historical_max_drawdown(db) -> float:
    equities = [
        float(row[0])
        for row in db.query(AccountSnapshot.equity).order_by(AccountSnapshot.id).all()
        if row[0] is not None
    ]
    return max_drawdown_from_equities(equities)


def realized_pnl_for_utc_day(db, target_day: date | None = None) -> float:
    """Return realized trade PnL for one UTC calendar day.

    Daily risk must reset at the UTC day boundary. AccountSnapshot.daily_pnl is
    retained as an audit field, but risk and public reporting derive the live
    daily value from closed trades so a stale snapshot cannot carry yesterday's
    PnL into today's risk budget.
    """

    day = target_day or datetime.now(timezone.utc).date()
    value = (
        db.query(func.coalesce(func.sum(Trade.pnl), 0.0))
        .filter(
            Trade.close_time.isnot(None),
            func.date(Trade.close_time) == day.isoformat(),
        )
        .scalar()
    )
    return float(value or 0.0)


def trades_opened_on_utc_day(db, target_day: date | None = None) -> int:
    day = target_day or datetime.now(timezone.utc).date()
    return int(
        db.query(Trade)
        .filter(func.date(Trade.open_time) == day.isoformat())
        .count()
    )


def latest_account(db) -> dict:
    snap = db.query(AccountSnapshot).order_by(desc(AccountSnapshot.id)).first()
    if not snap:
        snap = AccountSnapshot(
            equity=REFERENCE_CAPITAL_USDT,
            balance=REFERENCE_CAPITAL_USDT,
            daily_pnl=0,
            total_pnl=0,
            max_drawdown=0,
        )
        db.add(snap)
        db.commit()
        db.refresh(snap)
    return {
        "equity": snap.equity,
        "balance": snap.balance,
        "daily_pnl": snap.daily_pnl,
        "total_pnl": snap.total_pnl,
        "max_drawdown": historical_max_drawdown(db),
    }
