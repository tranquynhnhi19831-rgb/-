from sqlalchemy import desc
from models.account_snapshot import AccountSnapshot


def latest_account(db) -> dict:
    snap = db.query(AccountSnapshot).order_by(desc(AccountSnapshot.id)).first()
    if not snap:
        snap = AccountSnapshot(equity=20, balance=20, daily_pnl=0, total_pnl=0, max_drawdown=0)
        db.add(snap)
        db.commit()
        db.refresh(snap)
    return {
        "equity": snap.equity,
        "balance": snap.balance,
        "daily_pnl": snap.daily_pnl,
        "total_pnl": snap.total_pnl,
        "max_drawdown": snap.max_drawdown,
    }
