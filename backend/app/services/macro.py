"""Forex macro-news adapter — the 4th signal source, FOREX ONLY (not stocks/crypto).

The safety property (load-bearing): Claude scores each CURRENCY's macro bias
independently — it never decides a base/quote pair's direction. Code then derives
each PAIR's direction deterministically by arithmetic:

    net = signed_bias[BASE] − signed_bias[QUOTE]
    direction = bullish if net > 0 else bearish ; conviction = min(|net|, 1.0)

So one macro event (e.g. a hawkish Fed → bullish USD) mechanically produces
OPPOSITE correct directions across pairs: bearish EUR/USD, bullish USD/JPY.

Gold (XAU-USD) is SPECIAL-CASED: a direct per-pair read from gold-specific drivers
(real yields, USD, risk sentiment, central-bank buying) — NOT decomposed as a
pseudo-currency (that would double-count USD; gold isn't a currency).

Fail-safe-to-neutral: when Claude can't verify a currency it returns
bias="insufficient"; that currency signs to None and any pair touching it yields
NO news reading (the fusion nudge is simply skipped). We never fabricate a
direction from thin data — verified against real web_search behaviour.

Data source = Claude web_search (Trading Economics free tier was discontinued,
HTTP 410). Runs ~every 4h on Sonnet — macro moves slowly and news is confirm-only.
"""
import os
import json
import re
import datetime
from typing import Optional

import anthropic
from sqlalchemy.orm import Session

from app.models.models import MacroBias, SourceConfig

# Sonnet: good read-and-synthesize at ~1/3 Opus cost; macro is confirm-only.
DEFAULT_MODEL = "claude-sonnet-4-6"
# 6 currencies + gold. Configurable via the 'macro' source row's options.currencies.
DEFAULT_CURRENCIES = ["USD", "EUR", "JPY", "GBP", "CHF", "AUD"]
# Sized so one pass reliably covers all currencies + gold (probe showed too-low
# budgets make the model run dry and (correctly) refuse rather than fabricate).
DEFAULT_MAX_USES = 12
# Scheduled run times (UTC, "HH:MM"). 1 entry = once/day, 2 = twice/day. UI-tunable
# via options.run_times. Default once/day at 13:00 UTC (after the morning US/EU data drop).
DEFAULT_RUN_TIMES = ["13:00"]
# 80h — long enough to BRIDGE the forex weekend: Friday's macro (no weekend
# releases happen) stays applied through Monday's reopen until the next refresh,
# and it comfortably covers the once-daily gap so news never goes dark mid-week.
DEFAULT_FRESHNESS = 288000

# Forex weekend (UTC), inclusive of the close edge: market is CLOSED from
# Friday 22:00 through Sunday 22:00. weekday(): Mon=0 … Sun=6.
FOREX_CLOSE_HOUR = 22  # Friday
FOREX_OPEN_HOUR = 22   # Sunday

_VALID_CCY_BIAS = {"bullish", "bearish", "neutral"}   # anything else (incl. "insufficient") → None
_VALID_GOLD_DIR = {"bullish", "bearish", "neutral"}

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


def _system(currencies):
    ccy_list = ", ".join(currencies)
    return (
        "You are a forex macro analyst for an automated trading system. Use web search to "
        "find the most recent and imminent HIGH-IMPACT macro releases — central-bank rate "
        "decisions and guidance, CPI/inflation, employment (e.g. NFP), GDP, and PMI — for "
        f"each of these economies/currencies: {ccy_list}. Then judge each CURRENCY's near-term "
        "directional bias ON ITS OWN (do NOT think in pairs — never mention EUR/USD etc.). "
        "Separately, judge GOLD (XAU/USD) DIRECTLY from gold's own drivers (USD direction, real "
        "yields, risk sentiment, central-bank buying) — treat gold as gold, not as a currency.\n\n"
        "CRITICAL — never fabricate. If web search does not give you enough verified, current "
        "data to judge a currency, set its bias to \"insufficient\" (NOT a guess). Same for gold: "
        "use \"insufficient\" when unsure. A wrong guess is far worse than an honest abstention.\n\n"
        "strength is 0.0–1.0 conviction (0 = no edge, 1 = very strong). Use 'neutral' (with low "
        "strength) when releases are mixed or offsetting; use 'insufficient' only when you lack "
        "verified data. Keep each 'why' to one sentence citing the specific event/data.\n\n"
        "End your reply with ONLY this JSON object in a ```json fenced block (no prose after it):\n"
        '{"currencies": {'
        + ", ".join(
            f'"{c}": {{"bias": "bullish|bearish|neutral|insufficient", "strength": 0.0, "why": "..."}}'
            for c in currencies
        )
        + '}, "gold": {"direction": "bullish|bearish|neutral|insufficient", "strength": 0.0, "why": "..."}}'
    )


def _extract_json(text: str) -> Optional[dict]:
    """Pull the bias object out of the model's reply. Prefer a ```json fence;
    fall back to the last balanced {...}. Returns None on any failure (fail-safe:
    no snapshot rather than a malformed one)."""
    if not text:
        return None
    candidates = []
    fence = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates.extend(fence)
    # Greedy last-object fallback (covers replies with no fence).
    brace = re.findall(r"(\{.*\})", text, re.DOTALL)
    candidates.extend(brace)
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict) and "currencies" in obj:
            return obj
    return None


def fetch_macro_bias(db: Session, cfg: Optional[SourceConfig] = None):
    """Run one web_search-backed macro read and persist a MacroBias snapshot.
    Returns the row, or None if disabled / no usable output."""
    if cfg is None:
        cfg = db.query(SourceConfig).filter(SourceConfig.source == "macro").first()
    if cfg is not None and not cfg.enabled:
        return None

    opts = (cfg.options if cfg is not None and cfg.options else {}) or {}
    model = opts.get("model", DEFAULT_MODEL)
    currencies = opts.get("currencies", DEFAULT_CURRENCIES)
    max_uses = int(opts.get("max_uses", DEFAULT_MAX_USES))
    today = datetime.datetime.utcnow().date().isoformat()

    resp = _get_client().messages.create(
        model=model,
        max_tokens=4000,
        system=_system(currencies),
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}],
        messages=[{
            "role": "user",
            "content": (
                f"Today is {today}. Research the latest high-impact macro for each currency and "
                "gold, then produce the per-currency bias table. Remember: score each currency on "
                "its own, gold directly, and use \"insufficient\" rather than guessing."
            ),
        }],
    )

    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    data = _extract_json(text)
    if not data or not isinstance(data.get("currencies"), dict):
        return None  # fail-safe: no snapshot beats a bad one

    row = MacroBias(
        currencies=data.get("currencies"),
        gold=data.get("gold"),
        model=model,
        raw=text[:8000],
        timestamp=datetime.datetime.utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- deterministic per-pair derivation (the safety core) --------------------

def _signed(entry) -> Optional[float]:
    """Currency bias → signed magnitude in [-1, 1], or None when not usable
    (missing / "insufficient" / unknown). None propagates to 'no reading'."""
    if not isinstance(entry, dict):
        return None
    bias = entry.get("bias")
    if bias not in _VALID_CCY_BIAS:
        return None  # "insufficient" and anything unexpected → refuse
    try:
        s = float(entry.get("strength", 0) or 0)
    except (TypeError, ValueError):
        return None
    s = max(0.0, min(1.0, s))
    if bias == "bullish":
        return s
    if bias == "bearish":
        return -s
    return 0.0  # neutral


def pair_reading(symbol: str, snapshot: MacroBias) -> Optional[dict]:
    """Derive a pair's macro news direction from a snapshot.
    Returns {"direction": bullish|bearish|none, "conviction": 0..1} or None
    (None = no usable reading → fusion skips the news nudge entirely)."""
    if snapshot is None:
        return None
    sym = (symbol or "").upper()
    if "-" not in sym:
        return None
    base, quote = sym.split("-", 1)

    # Gold: DIRECT read, never decomposed.
    if base == "XAU":
        gold = snapshot.gold or {}
        d = gold.get("direction")
        if d not in _VALID_GOLD_DIR:
            return None  # insufficient/unknown → no reading
        if d == "neutral":
            return {"direction": "none", "conviction": 0.0}
        try:
            s = float(gold.get("strength", 0) or 0)
        except (TypeError, ValueError):
            return None
        return {"direction": d, "conviction": max(0.0, min(1.0, s))}

    # Currency pair: base − quote arithmetic.
    cur = snapshot.currencies or {}
    b = _signed(cur.get(base))
    q = _signed(cur.get(quote))
    if b is None or q is None:
        return None  # either leg unverified → refuse the whole pair
    net = b - q
    if net == 0:
        return {"direction": "none", "conviction": 0.0}
    return {
        "direction": "bullish" if net > 0 else "bearish",
        "conviction": min(abs(net), 1.0),
    }


def latest_snapshot(db: Session, freshness_seconds: int = DEFAULT_FRESHNESS) -> Optional[MacroBias]:
    """Most recent macro snapshot within the freshness window, else None."""
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(seconds=freshness_seconds)
    return (
        db.query(MacroBias)
        .filter(MacroBias.timestamp >= cutoff)
        .order_by(MacroBias.timestamp.desc())
        .first()
    )


# --- schedule gating (forex session + cadence) ------------------------------

def forex_market_open(now: datetime.datetime, opts: Optional[dict] = None) -> bool:
    """True when the FOREX market is open. Forex trades 24/5; it's CLOSED from
    Friday close (default 22:00 UTC) through Sunday reopen (default 22:00 UTC).
    This is the forex weekend — NOT US stock hours: currencies trade around the
    clock on weekdays and macro releases don't land on weekends."""
    opts = opts or {}
    close_h = int(opts.get("forex_close_hour", FOREX_CLOSE_HOUR))
    open_h = int(opts.get("forex_open_hour", FOREX_OPEN_HOUR))
    dow = now.weekday()  # Mon=0 … Fri=4, Sat=5, Sun=6
    if dow == 5:                               # Saturday — closed all day
        return False
    if dow == 4 and now.hour >= close_h:       # Friday after close
        return False
    if dow == 6 and now.hour < open_h:         # Sunday before reopen
        return False
    return True


def _run_times(opts: dict):
    """Parse options.run_times → sorted list of (hour, minute) UTC tuples (max 2)."""
    raw = opts.get("run_times") or DEFAULT_RUN_TIMES
    out = []
    for s in list(raw)[:2]:
        try:
            h, m = str(s).split(":")
            h, m = int(h), int(m)
        except (ValueError, AttributeError):
            continue
        if 0 <= h < 24 and 0 <= m < 60:
            out.append((h, m))
    if not out:
        h, m = DEFAULT_RUN_TIMES[0].split(":")
        out = [(int(h), int(m))]
    return sorted(set(out))


def _most_recent_slot(now: datetime.datetime, run_times, opts: dict, skip_weekend: bool):
    """The most recent scheduled run datetime <= now. When skip_weekend is on,
    slots that fell during the forex weekend are SKIPPED (not deferred to reopen)
    — a weekend run_time simply doesn't fire; the next firing is the next weekday
    slot. Scans today + the prior 3 days to bridge the weekend."""
    best = None
    for day_off in range(0, 4):
        d = (now - datetime.timedelta(days=day_off)).date()
        for (h, m) in run_times:
            slot = datetime.datetime(d.year, d.month, d.day, h, m)
            if slot <= now and (not skip_weekend or forex_market_open(slot, opts)):
                if best is None or slot > best:
                    best = slot
    return best


def due_to_run(cfg: SourceConfig, now: datetime.datetime, last_ts) -> bool:
    """Should a fetch happen on this tick? True only when: enabled, (if skipping
    the weekend) the forex market is open NOW, and there is a scheduled slot
    at/after the last snapshot (one fetch per slot — dedupes the frequent tick)."""
    if cfg is None or not cfg.enabled:
        return False
    opts = cfg.options or {}
    skip_weekend = opts.get("skip_forex_weekend", True)
    if skip_weekend and not forex_market_open(now, opts):
        return False
    slot = _most_recent_slot(now, _run_times(opts), opts, skip_weekend)
    if slot is None:
        return False
    return last_ts is None or last_ts < slot


def next_fetch_at(cfg: SourceConfig, now: Optional[datetime.datetime] = None):
    """The next actual macro fetch time (naive UTC) given run_times + the forex
    weekend skip — i.e. the next scheduled slot strictly after `now` that, when
    skip_forex_weekend is on, falls while the forex market is open. Pure schedule
    calc (ignores enabled); returns None if no slot found in the next 9 days."""
    now = now or datetime.datetime.utcnow()
    opts = (cfg.options if cfg is not None and cfg.options else {}) or {}
    skip_weekend = opts.get("skip_forex_weekend", True)
    run_times = _run_times(opts)
    for day_off in range(0, 9):
        d = (now + datetime.timedelta(days=day_off)).date()
        for (h, m) in run_times:
            slot = datetime.datetime(d.year, d.month, d.day, h, m)
            if slot > now and (not skip_weekend or forex_market_open(slot, opts)):
                return slot
    return None


def run_macro(db: Session, now: Optional[datetime.datetime] = None, force: bool = False):
    """Scheduler entry point — called on a frequent tick. Fetches a fresh macro
    snapshot only when due (enabled + forex open + a new scheduled slot). force=True
    bypasses the schedule gate (manual refresh / tests)."""
    now = now or datetime.datetime.utcnow()
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "macro").first()
    if cfg is None or not cfg.enabled:
        return None
    if not force:
        last = db.query(MacroBias).order_by(MacroBias.timestamp.desc()).first()
        last_ts = last.timestamp if last is not None else None
        if not due_to_run(cfg, now, last_ts):
            return None
    return fetch_macro_bias(db, cfg)
