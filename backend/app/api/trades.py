from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import ExecutedTrade, User
from app.core.deps import get_current_user, require_owner

router = APIRouter()


class ExecutedTradeSchema(BaseModel):
    id: int
    signal_id: Optional[int] = None
    asset: str
    side: Optional[str] = None
    entry_price: float
    exit_price: Optional[float] = None
    size: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    pnl: Optional[float] = None
    status: str
    close_reason: Optional[str] = None
    overrides: Optional[dict] = None
    entry_time: datetime
    exit_time: Optional[datetime] = None

    class Config:
        from_attributes = True


class TradeUpdate(BaseModel):
    overrides: Optional[dict] = None   # per-trade stop_loss/take_profit overrides
    close: Optional[bool] = None       # owner manual close at last marked price


@router.get("/", response_model=List[ExecutedTradeSchema])
def get_trades(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return (
        db.query(ExecutedTrade)
        .order_by(ExecutedTrade.entry_time.desc())
        .limit(200)
        .all()
    )


@router.put("/{trade_id}", response_model=ExecutedTradeSchema)
def update_trade(
    trade_id: int,
    payload: TradeUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    trade = db.query(ExecutedTrade).filter(ExecutedTrade.id == trade_id).first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")

    if payload.overrides is not None:
        trade.overrides = payload.overrides or None

    if payload.close and trade.status == "open":
        from app.services.risk import _latest_price, _position_pnl
        price = _latest_price(trade.asset, db)
        if price is None:
            raise HTTPException(status_code=502, detail="No price to close at")
        trade.exit_price = round(price, 6)
        trade.pnl = round(_position_pnl(trade, price), 4)
        trade.status = "closed"
        trade.close_reason = "manual"
        trade.exit_time = datetime.utcnow()

    db.commit()
    db.refresh(trade)
    return trade
