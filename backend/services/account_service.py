from sqlalchemy import desc

from config import REFERENCE_CAPITAL_USDT
from models.account_snapshot import AccountSnapshot


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
