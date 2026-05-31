from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import ExecutedTrade, User
from app.core.deps import get_current_user
from typing import List
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class ExecutedTradeSchema(BaseModel):
    id: int
    asset: str
    entry_price: float
    exit_price: float = None
    size: float
    pnl: float = None
    status: str
    entry_time: datetime

    class Config:
        from_attributes = True

@router.get("/", response_model=List[ExecutedTradeSchema])
def get_trades(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(ExecutedTrade).all()
