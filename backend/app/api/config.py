from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import SourceConfig, User
from app.core.deps import require_owner
from app.core.crypto import encrypt

router = APIRouter()


class SourceConfigUpdate(BaseModel):
    provider: Optional[str] = None
    enabled: Optional[bool] = None
    weight: Optional[float] = None
    freshness_seconds: Optional[int] = None
    interval_seconds: Optional[int] = None
    options: Optional[dict] = None
    credential: Optional[str] = None  # plaintext; encrypted server-side, never stored raw
    clear_credential: bool = False


def _serialize(row: SourceConfig) -> dict:
    return {
        "source": row.source,
        "provider": row.provider,
        "has_credential": row.credentials_encrypted is not None,
        "enabled": row.enabled,
        "weight": row.weight,
        "freshness_seconds": row.freshness_seconds,
        "interval_seconds": row.interval_seconds,
        "options": row.options,
        "updated_at": row.updated_at,
    }


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    rows = db.query(SourceConfig).order_by(SourceConfig.source).all()
    return [_serialize(r) for r in rows]


@router.put("/sources/{source}")
def update_source(
    source: str,
    payload: SourceConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    row = db.query(SourceConfig).filter(SourceConfig.source == source).first()
    if not row:
        raise HTTPException(status_code=404, detail="Unknown source")

    if payload.provider is not None:
        row.provider = payload.provider
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.weight is not None:
        row.weight = payload.weight
    if payload.freshness_seconds is not None:
        row.freshness_seconds = payload.freshness_seconds
    if payload.interval_seconds is not None:
        row.interval_seconds = payload.interval_seconds
    if payload.options is not None:
        row.options = payload.options

    if payload.clear_credential:
        row.credentials_encrypted = None
    elif payload.credential is not None:
        row.credentials_encrypted = encrypt(payload.credential)

    db.commit()
    db.refresh(row)
    return _serialize(row)
