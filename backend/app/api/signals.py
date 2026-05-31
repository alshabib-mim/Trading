from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import TradingSignal, AssetConfig, User
from app.core.deps import get_current_user
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

class TradingSignalSchema(BaseModel):
    id: int
    asset: str
    asset_type: Optional[str] = None  # stock | crypto | forex — so the UI can render every
                                      # enabled asset and label its direction source correctly
    direction: Optional[str] = None
    signal_type: Optional[str] = None  # null on watch rows (no armed direction)
    confidence_score: float
    direction_conviction: Optional[float] = None
    status: str
    # Which sources agreed with the read direction (null/false when no direction).
    technical_conf: Optional[bool] = None
    whale_conf: Optional[bool] = None
    sentiment_conf: Optional[bool] = None
    institutional_conf: Optional[bool] = None
    news_conf: Optional[bool] = None  # forex macro news confirms direction (forex only)
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
    # 200 rows comfortably covers the latest row for every enabled asset.
    rows = (
        db.query(TradingSignal)
        .order_by(TradingSignal.timestamp.desc())
        .limit(200)
        .all()
    )
    # Attach asset_type from the universe so the dashboard can render all assets
    # and pick the right direction-source label (insider / whale / technical).
    type_map = {a.symbol: a.asset_type for a in db.query(AssetConfig).all()}
    for r in rows:
        r.asset_type = type_map.get(r.asset)
    return rows
