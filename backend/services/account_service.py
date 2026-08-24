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
    with db.no_autoflush:
        equities = [
            float(row[0])
            for row in db.query(AccountSnapshot.equity).order_by(AccountSnapshot.id).all()
            if row[0] is not None
        ]
    return max_drawdown_from_equities(equities)


def realized_pnl_for_utc_day(db, target_day: date | None = None) -> float:
    """Return committed/previously-flushed realized PnL for one UTC day.

    The query deliberately runs under ``no_autoflush``. A caller may be in the
    middle of closing a Trade and need the *pre-close* daily ledger value before
    adding the new result. Letting SQLAlchemy autoflush that pending mutation
    would count the just-closed trade once in SQL and then a second time when
    the caller adds its PnL to build the new AccountSnapshot.

    Daily risk therefore remains deterministic across Session factories with
    either ``autoflush=True`` or ``autoflush=False``.
    """

    day = target_day or datetime.now(timezone.utc).date()
    with db.no_autoflush:
        value = (
            db.query(func.coalesce(func.sum(Trade.pnl), 0.0))
            .filter(
                Trade.close_time.isnot(None),
                func.date(Trade.close_time) == day.isoformat(),
            )
            .scalar()
        )
    return float(value or 0.0)


def consecutive_losses_for_utc_day(db, target_day: date | None = None) -> int:
    """Count the current realized-loss streak inside one UTC calendar day.

    The streak is based on trade *close* time because a win/loss becomes known
    only when realized. A position opened before midnight and closed after
    midnight therefore belongs to the new UTC day's cooldown. Previous-day
    losses can never permanently deadlock the next day.
    """

    day = target_day or datetime.now(timezone.utc).date()
    with db.no_autoflush:
        rows = (
            db.query(Trade.pnl)
            .filter(
                Trade.close_time.isnot(None),
                func.date(Trade.close_time) == day.isoformat(),
            )
            .order_by(desc(Trade.close_time), desc(Trade.id))
            .all()
        )

    count = 0
    for row in rows:
        pnl = float(row[0] or 0.0)
        if pnl < 0:
            count += 1
            continue
        break
    return count


def trades_opened_on_utc_day(db, target_day: date | None = None) -> int:
    day = target_day or datetime.now(timezone.utc).date()
    with db.no_autoflush:
        return int(
            db.query(Trade)
            .filter(func.date(Trade.open_time) == day.isoformat())
            .count()
        )


def latest_account(db) -> dict:
    with db.no_autoflush:
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
