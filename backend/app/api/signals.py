from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import TradingSignal, User
from app.core.deps import get_current_user
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class TradingSignalSchema(BaseModel):
    id: int
    asset: str
    direction: Optional[str] = None
    signal_type: Optional[str] = None  # null on watch rows (no armed direction)
    confidence_score: float
    status: str
    # Which sources agreed with the read direction (null/false when no direction).
    technical_conf: Optional[bool] = None
    whale_conf: Optional[bool] = None
    sentiment_conf: Optional[bool] = None
    institutional_conf: Optional[bool] = None
    reasoning: Optional[str] = None
    timestamp: datetime

    class Config:
        from_attributes = True

@router.get("/", response_model=List[TradingSignalSchema])
def get_signals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Newest first; cap the list so accumulating watch rows don't flood the UI.
    return (
        db.query(TradingSignal)
        .order_by(TradingSignal.timestamp.desc())
        .limit(200)
        .all()
    )
