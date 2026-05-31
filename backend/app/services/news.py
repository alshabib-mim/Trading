"""Finnhub news adapter — feeds per-ticker headlines to the Claude sentiment
scorer. Finnhub company-news is equities-only; crypto is skipped (sentiment is
confirm-only and crypto direction comes from whale flow).

Reads the Finnhub API key (decrypted) from the 'news' source config at runtime
(owner enters it in the config UI, encrypted — like the Whale Alert key).
Conservative refresh (hourly) to stay well under the free-tier rate limit.
"""
import datetime

import requests
from sqlalchemy.orm import Session

from app.models.models import SourceConfig
from app.core.crypto import decrypt
from app.services.ai_service import analyze_sentiment

_BASE = "https://finnhub.io/api/v1/company-news"


def fetch_company_news(symbol, api_key, lookback_days=2, max_headlines=15):
    today = datetime.date.today()
    params = {
        "symbol": symbol,
        "from": (today - datetime.timedelta(days=lookback_days)).isoformat(),
        "to": today.isoformat(),
        "token": api_key,
    }
    resp = requests.get(_BASE, params=params, timeout=20)
    resp.raise_for_status()
    items = resp.json() or []
    headlines = []
    for it in items:
        h = (it.get("headline") or "").strip()
        if h:
            headlines.append(h)
        if len(headlines) >= max_headlines:
            break
    return headlines


def run_sentiment(assets, db: Session):
    """Scheduler entry point. No-op unless the 'news' source is enabled with a
    Finnhub key AND the 'sentiment' (Claude scorer) source is enabled.
    """
    news_cfg = db.query(SourceConfig).filter(SourceConfig.source == "news").first()
    if news_cfg is None or not news_cfg.enabled or not news_cfg.credentials_encrypted:
        return []
    sent_cfg = db.query(SourceConfig).filter(SourceConfig.source == "sentiment").first()
    if sent_cfg is None or not sent_cfg.enabled:
        return []

    api_key = decrypt(news_cfg.credentials_encrypted)
    opts = news_cfg.options or {}
    lookback = opts.get("lookback_days", 2)
    max_headlines = opts.get("max_headlines", 15)

    readings = []
    for asset in assets:  # caller passes stock symbols only (Finnhub is equities)
        try:
            headlines = fetch_company_news(asset, api_key, lookback, max_headlines)
        except requests.RequestException:
            continue
        if not headlines:
            continue
        reading = analyze_sentiment(asset, headlines, db, cfg=sent_cfg)
        if reading:
            readings.append(reading)
    return readings
