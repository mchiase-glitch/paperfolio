from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import portfolio

router = APIRouter(prefix="/api/portfolio", tags=["portafoglio"])


@router.get("")
def get_portfolio(db: Session = Depends(get_db)):
    return portfolio.summary(db, portfolio.active_account(db))
