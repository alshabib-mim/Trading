"""Owner-only asset universe CRUD. Edits land in asset_config and are read by
the scheduler/fusion at runtime — add/remove takes effect on the next tick,
no redeploy (same live-switching as source_config).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import AssetConfig, User
from app.core.deps import require_owner

router = APIRouter()

VALID_TYPES = {"stock", "crypto"}


class AssetCreate(BaseModel):
    symbol: str
    asset_type: str
    enabled: bool = True


class AssetUpdate(BaseModel):
    asset_type: Optional[str] = None
    enabled: Optional[bool] = None


def _serialize(r: AssetConfig) -> dict:
    return {
        "symbol": r.symbol,
        "asset_type": r.asset_type,
        "enabled": bool(r.enabled),
        "updated_at": r.updated_at,
    }


@router.get("/")
def list_assets(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    rows = db.query(AssetConfig).order_by(AssetConfig.asset_type, AssetConfig.symbol).all()
    return [_serialize(r) for r in rows]


@router.post("/")
def add_asset(payload: AssetCreate, db: Session = Depends(get_db), _: User = Depends(require_owner)):
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol required")
    if payload.asset_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="asset_type must be 'stock' or 'crypto'")
    if payload.asset_type == "crypto" and not symbol.endswith("-USD"):
        raise HTTPException(status_code=400, detail="Crypto symbols must look like BASE-USD (e.g. SOL-USD)")
    if db.query(AssetConfig).filter(AssetConfig.symbol == symbol).first():
        raise HTTPException(status_code=400, detail="Asset already exists")
    row = AssetConfig(symbol=symbol, asset_type=payload.asset_type, enabled=payload.enabled)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.put("/{symbol}")
def update_asset(symbol: str, payload: AssetUpdate, db: Session = Depends(get_db), _: User = Depends(require_owner)):
    row = db.query(AssetConfig).filter(AssetConfig.symbol == symbol.upper()).first()
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    if payload.asset_type is not None:
        if payload.asset_type not in VALID_TYPES:
            raise HTTPException(status_code=400, detail="asset_type must be 'stock' or 'crypto'")
        row.asset_type = payload.asset_type
    if payload.enabled is not None:
        row.enabled = payload.enabled
    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.delete("/{symbol}")
def delete_asset(symbol: str, db: Session = Depends(get_db), _: User = Depends(require_owner)):
    row = db.query(AssetConfig).filter(AssetConfig.symbol == symbol.upper()).first()
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")
    db.delete(row)
    db.commit()
    return {"deleted": symbol.upper()}
