"""Claude reasoning layer. Called ONLY when a signal arms (status="pending") —
never on watch rows. Produces a short human-readable rationale stored on the
trading_signals row. Failures degrade to None (never block the signal).
"""
import os

import anthropic
from sqlalchemy.orm import Session

from app.models.models import SourceConfig

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You explain why an automated trading signal armed, for a human reviewer. "
    "You are given the asset, the proposed direction, the confidence, and which "
    "sources confirmed it (the direction source, technical timing, sentiment, and "
    "institutional 13F support). Write 2-3 plain sentences: what the signal is, why "
    "it armed (which sources agree), and the single biggest risk or caveat. Be "
    "concrete and sober. This is decision support, not financial advice — never "
    "tell the reviewer to buy or sell."
)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _model(db: Session):
    fcfg = db.query(SourceConfig).filter(SourceConfig.source == "fusion").first()
    opts = (fcfg.options if fcfg and fcfg.options else {}) or {}
    return opts.get("reasoning_model", DEFAULT_MODEL)


def _format(c):
    confirms = [
        name for name, ok in [
            ("technical timing", c.get("technical_conf")),
            ("sentiment", c.get("sentiment_conf")),
            ("institutional 13F", c.get("institutional_conf")),
            ("whale flow", c.get("whale_conf")),
            ("macro news", c.get("news_conf")),
        ] if ok
    ]
    return (
        f"Asset: {c['asset']}\n"
        f"Direction: {c['direction']}\n"
        f"Confidence: {c['confidence']:.2f}\n"
        f"Confirming sources: {', '.join(confirms) or 'none'}\n"
        f"Details: {c.get('detail', '')}"
    )


def generate_reasoning(context: dict, db: Session):
    """Return a short rationale string, or None on any failure."""
    try:
        response = _get_client().messages.create(
            model=_model(db),
            max_tokens=300,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _format(context)}],
        )
        parts = [b.text for b in response.content if b.type == "text"]
        return " ".join(parts).strip() or None
    except Exception:
        return None
