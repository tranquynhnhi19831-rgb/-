from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db
from services.account_service import latest_account

router = APIRouter(tags=["dashboard"])


@router.get("/api/account")
def account(db: Session = Depends(get_db)):
    return latest_account(db)
