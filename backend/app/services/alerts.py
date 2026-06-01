"""Outbound alerts — Telegram channel (free, no per-message cost).

Config-driven and UI-toggleable, same pattern as sources: a single alert_config
row holds the encrypted bot token + chat id and a per-event-type enable map, all
gated by a master `enabled` switch. Owner sets the token/chat-id in the Config UI
(encrypted at rest); nothing sends until they do and flip `enabled` on.

Four events: signal_armed, position_opened, exit_hit, breaker.

Hard rule: alerting must NEVER break the trading loop. Every public emitter
swallows its own exceptions and returns a bool — a Telegram outage or a bad
token can never raise into fusion or the risk engine.
"""
import logging

import requests
from sqlalchemy.orm import Session

from app.models.models import AlertConfig
from app.core.crypto import decrypt

logger = logging.getLogger("alerts")

# Default per-event enable map (all on — "sensible defaults but editable").
DEFAULT_EVENTS = {
    "signal_armed": True,
    "position_opened": True,
    "exit_hit": True,
    "breaker": True,
}
EVENT_TYPES = tuple(DEFAULT_EVENTS.keys())

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10


def get_config(db: Session):
    """The single alert_config row, or None if not seeded yet."""
    return db.query(AlertConfig).first()


def _creds(cfg: AlertConfig):
    """Decrypt (bot_token, chat_id). Returns (None, None) if missing/undecryptable."""
    try:
        token = decrypt(cfg.bot_token_encrypted) if cfg.bot_token_encrypted else None
        chat_id = decrypt(cfg.chat_id_encrypted) if cfg.chat_id_encrypted else None
        return token, chat_id
    except Exception:
        logger.exception("alerts: failed to decrypt credentials")
        return None, None


def send_message(text: str, db: Session, cfg: AlertConfig = None):
    """Low-level Telegram send. Returns (ok: bool, detail: str). Used by both the
    event emitters and the /test endpoint. Does NOT check the master/event toggles
    — callers decide that (so a test can send while alerts are otherwise off)."""
    cfg = cfg or get_config(db)
    if cfg is None:
        return False, "alerts not configured"
    token, chat_id = _creds(cfg)
    if not token or not chat_id:
        return False, "bot token and chat id are required"
    try:
        resp = requests.post(
            _TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("alerts: telegram request failed: %s", exc)
        return False, f"network error: {exc}"
    if resp.status_code == 200 and resp.json().get("ok"):
        return True, "sent"
    # Surface Telegram's own error (e.g. "chat not found", "Unauthorized") to the UI.
    try:
        detail = resp.json().get("description", resp.text)
    except ValueError:
        detail = resp.text
    logger.warning("alerts: telegram rejected (%s): %s", resp.status_code, detail)
    return False, f"telegram error: {detail}"


def _emit(event_type: str, text: str, db: Session):
    """Send an event alert iff master-enabled AND this event type is on. Swallows
    all errors — alerting never propagates into the caller."""
    try:
        cfg = get_config(db)
        if cfg is None or not cfg.enabled:
            return False
        events = cfg.events if cfg.events is not None else DEFAULT_EVENTS
        if not events.get(event_type, True):
            return False
        ok, _ = send_message(text, db, cfg)
        return ok
    except Exception:
        logger.exception("alerts: _emit failed for %s", event_type)
        return False


# --- message builders + public emitters (one per event) ---------------------

def _confirmers(sig):
    names = []
    for attr, label in (("technical_conf", "technical"), ("sentiment_conf", "sentiment"),
                        ("institutional_conf", "13F"), ("whale_conf", "whale"),
                        ("news_conf", "macro news")):
        if getattr(sig, attr, None):
            names.append(label)
    return ", ".join(names) or "—"


def signal_armed(sig, db: Session):
    """Fired when a signal transitions watch → pending (arms)."""
    conf = round((sig.confidence_score or 0) * 100)
    text = (
        f"🟢 SIGNAL ARMED\n"
        f"{sig.asset} · {str(sig.direction).upper()} · {sig.signal_type or '—'}\n"
        f"Confidence {conf}%\n"
        f"Confirmed by: {_confirmers(sig)}"
    )
    return _emit("signal_armed", text, db)


def position_opened(trade, db: Session):
    """Fired when a paper position opens."""
    text = (
        f"📈 POSITION OPENED\n"
        f"{trade.asset} · {str(trade.side).upper()}\n"
        f"Entry {trade.entry_price} · size {trade.size}\n"
        f"Stop {trade.stop_loss if trade.stop_loss is not None else '—'} · "
        f"Target {trade.take_profit if trade.take_profit is not None else '—'}"
    )
    return _emit("position_opened", text, db)


def exit_hit(trade, db: Session):
    """Fired when an open position closes on a stop or target."""
    icon = "🛑" if trade.close_reason == "stop" else "🎯"
    label = "STOP HIT" if trade.close_reason == "stop" else "TARGET HIT"
    pnl = trade.pnl if trade.pnl is not None else 0.0
    sign = "+" if pnl >= 0 else "-"
    text = (
        f"{icon} {label}\n"
        f"{trade.asset} · {str(trade.side).upper()} closed\n"
        f"Exit {trade.exit_price} · PnL {sign}${abs(pnl):,.2f}"
    )
    return _emit("exit_hit", text, db)


def breaker_fired(reasons, equity, db: Session):
    """Fired when a circuit breaker engages (daily loss / drawdown / manual halt)."""
    text = (
        f"🚨 CIRCUIT BREAKER\n"
        f"Trading halted: {', '.join(reasons)}\n"
        f"Equity ${equity:,.2f}\n"
        f"New positions are blocked until cleared."
    )
    return _emit("breaker", text, db)
