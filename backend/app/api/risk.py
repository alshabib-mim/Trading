"""Owner-only risk config + state API. Same pattern as source_config:
config is editable, state is read-only (engine-written) except the manual halt.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import RiskConfig, RiskState, User
from app.core.deps import require_owner
from app.services import risk as risk_engine

router = APIRouter()


class RiskConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    params: Optional[dict] = None


class StateUpdate(BaseModel):
    manual_halt: Optional[bool] = None


def _serialize_cfg(row: RiskConfig) -> dict:
    return {
        "key": row.key,
        "enabled": bool(row.enabled),
        "params": row.params or {},
        "updated_at": row.updated_at,
    }


@router.get("/config")
def list_config(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    rows = db.query(RiskConfig).order_by(RiskConfig.key).all()
    return [_serialize_cfg(r) for r in rows]


@router.put("/config/{key}")
def update_config(
    key: str,
    payload: RiskConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    row = db.query(RiskConfig).filter(RiskConfig.key == key).first()
    if not row:
        raise HTTPException(status_code=404, detail="Unknown risk config key")
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.params is not None:
        row.params = {**(row.params or {}), **payload.params}
    db.commit()
    db.refresh(row)
    return _serialize_cfg(row)


@router.get("/state")
def get_state(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    cfg_map = risk_engine._config_map(db)
    capital, _, _ = risk_engine._account(cfg_map)
    state = risk_engine._get_state(db)
    equity, realized, unreal = risk_engine.compute_equity(db, capital)
    halt = risk_engine.check_halt(db, cfg_map, equity, capital, state)
    dd = 0.0
    if state.peak_equity:
        dd = max(0.0, (state.peak_equity - equity) / state.peak_equity)
    return {
        "starting_capital": capital,
        "equity": round(equity, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": round(unreal, 2),
        "peak_equity": round(state.peak_equity, 2) if state.peak_equity else None,
        "drawdown_pct": round(dd * 100, 2),
        "daily_pnl": round(risk_engine._daily_realized_pnl(db), 2),
        "manual_halt": bool(state.manual_halt),
        "halted": bool(halt),
        "halt_reasons": halt,
    }


@router.put("/state")
def update_state(
    payload: StateUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    state = risk_engine._get_state(db)
    if payload.manual_halt is not None:
        state.manual_halt = payload.manual_halt
    db.commit()
    return {"manual_halt": bool(state.manual_halt)}
