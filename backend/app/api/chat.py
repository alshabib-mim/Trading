"""Owner-only chat assistant API.

/message  — one assistant turn over the live snapshot; may return a staged proposal.
/confirm  — apply or cancel a staged proposal (the ONLY path that mutates state).
/audit    — recent action log (who/what/when/before→after).

All endpoints require_owner. The model never applies anything: it proposes via the
chat_actions enforcer, and only an explicit /confirm with the server-issued
action_id applies the change (re-validated + stale-guarded server-side).
"""
from typing import List, Literal, Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import User, ChatAction
from app.core.deps import require_owner
from app.services import chat_assistant, chat_actions

router = APIRouter()

MAX_MESSAGES = 40
MAX_CHARS = 8000


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(default_factory=list)


class ConfirmRequest(BaseModel):
    action_id: str
    decision: Literal["confirm", "cancel"]


@router.post("/message")
def post_message(payload: ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_owner)):
    msgs = payload.messages[-MAX_MESSAGES:]
    if not msgs or msgs[-1].role != "user":
        raise HTTPException(status_code=400, detail="last message must be from the user")
    if any(len(m.content) > MAX_CHARS for m in msgs):
        raise HTTPException(status_code=400, detail="message too long")
    convo = [{"role": m.role, "content": m.content} for m in msgs]
    try:
        return chat_assistant.chat(convo, db, user.username)
    except Exception as exc:  # noqa: BLE001 — surface upstream (model) errors cleanly
        raise HTTPException(status_code=502, detail=f"assistant error: {exc}")


@router.post("/confirm")
def post_confirm(payload: ConfirmRequest, db: Session = Depends(get_db), user: User = Depends(require_owner)):
    try:
        return chat_actions.confirm(db, user.username, payload.action_id, payload.decision)
    except chat_actions.Rejection as exc:
        raise HTTPException(status_code=409, detail=exc.message)


@router.get("/audit")
def get_audit(limit: int = 50, db: Session = Depends(get_db), _: User = Depends(require_owner)):
    limit = max(1, min(limit, 200))
    rows = db.query(ChatAction).order_by(ChatAction.created_at.desc()).limit(limit).all()
    return [{
        "action_id": r.action_id, "username": r.username, "target": r.target, "label": r.label,
        "before": r.before_value, "after": r.after_value, "status": r.status,
        "reason": r.reason, "risk_note": r.risk_note,
        "created_at": r.created_at, "resolved_at": r.resolved_at,
    } for r in rows]
