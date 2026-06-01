"""Market open/close status per asset type.

  stocks  — US regular hours (09:30–16:00 ET, Mon–Fri). yfinance is regular-hours
            only; holidays are not tracked here.
  crypto  — 24/7, always open.
  forex   — 24/5, open Sun 22:00 UTC → Fri 22:00 UTC. REUSES the existing
            macro.forex_market_open weekend logic — not duplicated.
"""
import datetime
from datetime import timezone

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 — tz database unavailable
    _NY = None

from app.services import macro


def stock_status(now: datetime.datetime = None):
    now = now or datetime.datetime.utcnow()
    if _NY is None:
        return {"open": False, "label": "US market", "detail": "timezone data unavailable"}
    ny = now.replace(tzinfo=timezone.utc).astimezone(_NY)
    weekday = ny.weekday() < 5
    minutes = ny.hour * 60 + ny.minute
    is_open = weekday and (9 * 60 + 30) <= minutes < (16 * 60)
    return {
        "open": is_open,
        "label": "US market (NYSE/Nasdaq)",
        "detail": "regular hours 9:30–16:00 ET, Mon–Fri — yfinance is regular-hours only (holidays not tracked)",
    }


def crypto_status(now: datetime.datetime = None):
    return {"open": True, "label": "Crypto", "detail": "24/7 — always open"}


def forex_status(now: datetime.datetime = None):
    now = now or datetime.datetime.utcnow()
    is_open = macro.forex_market_open(now)  # reuse the weekend-skip session logic
    return {
        "open": is_open,
        "label": "Forex / gold",
        "detail": "24/5 — open Sun 22:00 → Fri 22:00 UTC" + ("" if is_open else " (weekend closed)"),
    }


def all_markets(now: datetime.datetime = None):
    now = now or datetime.datetime.utcnow()
    return {
        "stock": stock_status(now),
        "crypto": crypto_status(now),
        "forex": forex_status(now),
    }
