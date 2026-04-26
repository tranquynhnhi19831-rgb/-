from __future__ import annotations

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
        "source": "local_snapshot",
    }


def build_account_state(cfg: dict, db, client=None) -> dict:
    if cfg["dry_run"] or client is None:
        acc = latest_account(db)
        acc["source"] = "simulation"
        return {**acc, "positions": [], "open_orders": []}

    try:
        futures = client.fetch_futures_account()
        positions = [p for p in client.fetch_positions() if abs(float(p.get("contracts") or 0)) > 0]
        open_orders = client.fetch_open_orders()
        return {
            "equity": futures["wallet"],
            "balance": futures["free"],
            "daily_pnl": 0,
            "total_pnl": 0,
            "max_drawdown": 0,
            "source": "binance_testnet" if cfg["testnet"] else "binance_live",
            "positions": positions,
            "open_orders": open_orders,
        }
    except Exception:
        acc = latest_account(db)
        acc["source"] = "fallback_snapshot"
        return {**acc, "positions": [], "open_orders": []}
