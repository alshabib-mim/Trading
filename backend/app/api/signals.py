from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import TradingSignal, User
from app.core.deps import get_current_user
from typing import List
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class TradingSignalSchema(BaseModel):
    id: int
    asset: str
    signal_type: str
    confidence_score: float
    status: str
    timestamp: datetime

    class Config:
        from_attributes = True

@router.get("/", response_model=List[TradingSignalSchema])
def get_signals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return db.query(TradingSignal).all()
