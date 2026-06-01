"""Owner-only alerts configuration (Telegram). Bot token + chat id are stored
AES-256-GCM encrypted (same as source credentials) and never returned to the
client — the GET only reports whether each is set. POST /test sends a live
message so the owner can confirm the wiring after pasting their credentials.
"""
from typing import Optional, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import AlertConfig, User
from app.core.deps import require_owner
from app.core.crypto import encrypt
from app.services import alerts

router = APIRouter()


class AlertConfigUpdate(BaseModel):
    enabled: Optional[bool] = None
    events: Optional[Dict[str, bool]] = None
    bot_token: Optional[str] = None        # plaintext in; encrypted server-side
    chat_id: Optional[str] = None          # plaintext in; encrypted server-side
    clear_bot_token: bool = False
    clear_chat_id: bool = False


def _row(db: Session) -> AlertConfig:
    row = db.query(AlertConfig).first()
    if row is None:
        # Self-heal if the seed row is somehow missing.
        row = AlertConfig(channel="telegram", enabled=False, events=dict(alerts.DEFAULT_EVENTS))
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _serialize(row: AlertConfig) -> dict:
    return {
        "channel": row.channel,
        "enabled": bool(row.enabled),
        "has_bot_token": row.bot_token_encrypted is not None,
        "has_chat_id": row.chat_id_encrypted is not None,
        "events": row.events if row.events is not None else dict(alerts.DEFAULT_EVENTS),
        "event_types": list(alerts.EVENT_TYPES),
        "updated_at": row.updated_at,
    }


@router.get("/")
def get_alerts(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    return _serialize(_row(db))


@router.put("/")
def update_alerts(
    payload: AlertConfigUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_owner),
):
    row = _row(db)
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.events is not None:
        # Only persist known event keys; default any missing to current/true.
        merged = dict(row.events if row.events is not None else alerts.DEFAULT_EVENTS)
        for k in alerts.EVENT_TYPES:
            if k in payload.events:
                merged[k] = bool(payload.events[k])
        row.events = merged

    if payload.clear_bot_token:
        row.bot_token_encrypted = None
    elif payload.bot_token:
        row.bot_token_encrypted = encrypt(payload.bot_token.strip())

    if payload.clear_chat_id:
        row.chat_id_encrypted = None
    elif payload.chat_id:
        row.chat_id_encrypted = encrypt(payload.chat_id.strip())

    db.commit()
    db.refresh(row)
    return _serialize(row)


@router.post("/test")
def test_alert(db: Session = Depends(get_db), _: User = Depends(require_owner)):
    """Send a live test message. Works regardless of the master/event toggles so
    the owner can verify credentials before turning alerts on."""
    row = _row(db)
    if row.bot_token_encrypted is None or row.chat_id_encrypted is None:
        raise HTTPException(status_code=400, detail="Add the bot token and chat id first")
    ok, detail = alerts.send_message(
        "✅ Test alert from your trading system — Telegram is wired up correctly.",
        db, row,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=detail)
    return {"sent": True, "detail": detail}
