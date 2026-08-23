from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import get_db
from services.account_service import latest_account, realized_pnl_for_utc_day

router = APIRouter(tags=["dashboard"])


@router.get("/api/account")
def account(db: Session = Depends(get_db)):
    result = latest_account(db)
    result["daily_pnl"] = realized_pnl_for_utc_day(db)
    return result
