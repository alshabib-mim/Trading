"""Claude sentiment adapter. Sentiment only CONFIRMS or DAMPENS a signal — it
never sets direction on its own (role="confirm"). Returns a normalized 0.0–1.0
score where 0 = bearish, 0.5 = neutral, 1 = bullish.

Uses structured output (messages.parse + a Pydantic schema) so the result is
always valid JSON — no fragile text parsing. Model is read from the sentiment
source's config options at runtime (default claude-opus-4-8), so it can be
switched in the config UI without a redeploy.
"""
import os
import datetime
from typing import Literal, Optional

import anthropic
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.models.models import SentimentScore, SourceConfig

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are a market-sentiment classifier for a trading system. You read recent "
    "news headlines about a single asset and judge the overall sentiment. Sentiment "
    "only CONFIRMS or DAMPENS a trading signal that other sources have already "
    "produced — it never sets direction on its own. Be conservative: when headlines "
    "are mixed, routine, or ambiguous, answer 'neutral' with low confidence. Judge "
    "only from the headlines provided; do not use outside knowledge."
)

_client = None


class SentimentResult(BaseModel):
    sentiment: Literal["positive", "neutral", "negative"]
    confidence: float  # 0.0–1.0: how clear/strong the sentiment is
    rationale: str     # one concise sentence


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _unit_score(sentiment: str, confidence: float) -> float:
    # Map onto 0..1: bearish < 0.5 < bullish, magnitude scaled by confidence.
    c = max(0.0, min(1.0, confidence))
    if sentiment == "positive":
        return round(0.5 + 0.5 * c, 4)
    if sentiment == "negative":
        return round(0.5 - 0.5 * c, 4)
    return 0.5


def analyze_sentiment(asset: str, headlines: list, db: Session, cfg: Optional[SourceConfig] = None):
    """Classify sentiment for an asset from a list of headlines.

    Returns a normalized SourceReading dict, or None if disabled / no headlines.
    """
    if cfg is None:
        cfg = db.query(SourceConfig).filter(SourceConfig.source == "sentiment").first()
    if cfg is not None and not cfg.enabled:
        return None
    if not headlines:
        return None

    options = cfg.options if cfg is not None and cfg.options else {}
    model = options.get("model", DEFAULT_MODEL)

    headline_block = "\n".join(f"- {h}" for h in headlines)
    response = _get_client().messages.parse(
        model=model,
        max_tokens=512,
        system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": f"Asset: {asset}\nRecent headlines:\n{headline_block}",
        }],
        output_format=SentimentResult,
    )
    result = response.parsed_output
    if result is None:
        return None

    score = _unit_score(result.sentiment, result.confidence)

    row = SentimentScore(
        asset=asset,
        score=score,            # normalized 0..1 (0=bearish, 0.5=neutral, 1=bullish)
        rationale=result.rationale,
        headlines=list(headlines),  # the exact headlines scored
        source="claude",
    )
    db.add(row)
    db.commit()

    direction = (
        "bullish" if result.sentiment == "positive"
        else "bearish" if result.sentiment == "negative"
        else "none"
    )
    return {
        "source": "sentiment",
        "asset": asset,
        "direction": direction,
        "score": score,
        "role": "confirm",  # confirms/dampens only — never arms a signal alone
        "detail": f"{result.sentiment} ({result.confidence:.2f}): {result.rationale}",
        "observed_at": datetime.datetime.utcnow().isoformat(),
    }
