from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db
from services.account_service import latest_account
from services.trading_engine import ENGINE

router = APIRouter(tags=["dashboard"])


@router.get("/api/account")
def account(db: Session = Depends(get_db)):
    if ENGINE.last_account_state:
        return ENGINE.last_account_state
    return latest_account(db)


@router.get("/api/open-orders")
def open_orders(db: Session = Depends(get_db)):
    return (ENGINE.last_account_state or {}).get("open_orders", [])
