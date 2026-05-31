"""Signal-fusion engine. Per asset per cycle, reads the freshest reading from
each ENABLED source (derived from its persisted table — the adapters are left
untouched), combines them by role, and writes ONE trading_signals row.

Roles:
  DIRECTION (arms): insider (Form 4) for stocks, whale for crypto.
  TIMING  (hard gate): technical — strength = fraction of indicators agreeing.
  CONFIRM/SUPPORT (nudge only, never arms): sentiment, 13F.

Score conventions differ by source (Option A — fusion interprets per-source):
  centered (whale, sentiment): 0.5 = neutral; conviction = |s - 0.5| * 2
  magnitude (insider, 13F):    0 = nothing, 1 = strong; conviction = s

A row is ARMED (status="pending") only when there is a direction, technical
agrees with it (hard gate), and confidence >= arm_threshold. Otherwise it is a
lean WATCH row (status="watch") — distinguishes "ran but nothing" from "broken"
(no row). Reasoning (reasoning.py) is only called on armed rows.
"""
import datetime

from sqlalchemy.orm import Session

from app.models.models import (
    TradingSignal, TechnicalSignal, InsiderTransaction, WhaleMovement,
    SentimentScore, InstitutionalPosition, SourceConfig,
)
from app.services.market_data import is_crypto

# Fusion defaults — overridden by the 'fusion' source_config row's options.
DEFAULTS = {
    "arm_threshold": 0.6,
    "w_direction": 0.6,
    "w_sentiment": 0.15,
    "w_support": 0.1,
}


def _cfg(db, source):
    return db.query(SourceConfig).filter(SourceConfig.source == source).first()


def _enabled(cfg):
    return cfg is not None and cfg.enabled


def _freshness(cfg, default):
    if cfg is not None and cfg.freshness_seconds:
        return cfg.freshness_seconds
    return default


# --- per-source readings (derived from persisted rows) ----------------------

def _technical_reading(asset, db, cfg, now):
    if not _enabled(cfg):
        return None
    cutoff = now - datetime.timedelta(seconds=_freshness(cfg, 3600))
    rows = (
        db.query(TechnicalSignal)
        .filter(TechnicalSignal.asset == asset, TechnicalSignal.timestamp >= cutoff)
        .all()
    )
    if not rows:
        return None
    latest = {}
    for r in rows:
        cur = latest.get(r.indicator_name)
        if cur is None or r.timestamp > cur.timestamp:
            latest[r.indicator_name] = r
    votes = [r.signal_type for r in latest.values()]
    buys, sells, n = votes.count("buy"), votes.count("sell"), len(votes)
    if buys > sells:
        return {"role": "timing", "direction": "bullish", "strength": round(buys / n, 4)}
    if sells > buys:
        return {"role": "timing", "direction": "bearish", "strength": round(sells / n, 4)}
    return {"role": "timing", "direction": "none", "strength": 0.0}


def _insider_reading(asset, db, cfg, now):
    if not _enabled(cfg):
        return None
    opts = cfg.options or {}
    cutoff = now - datetime.timedelta(seconds=_freshness(cfg, 1209600))
    rows = (
        db.query(InsiderTransaction)
        .filter(InsiderTransaction.ticker == asset, InsiderTransaction.filed_date >= cutoff)
        .all()
    )
    if not rows:
        return None
    buyers = {r.insider_name for r in rows}
    net = sum(r.value or 0.0 for r in rows)
    bscale = opts.get("buyer_scale", 3)
    vscale = opts.get("value_scale", 500000)
    score = 0.6 * min(len(buyers) / bscale, 1.0) + 0.4 * min(net / vscale, 1.0)
    return {"role": "direction", "direction": "bullish", "conviction": round(min(score, 1.0), 4)}


def _whale_reading(asset, db, cfg, now):
    if not _enabled(cfg):
        return None
    opts = cfg.options or {}
    cutoff = now - datetime.timedelta(seconds=_freshness(cfg, 3600))
    rows = (
        db.query(WhaleMovement)
        .filter(WhaleMovement.asset == asset, WhaleMovement.timestamp >= cutoff)
        .all()
    )
    if not rows:
        return None
    scale = opts.get("scale", 50_000_000)
    bull = sum(r.amount or 0.0 for r in rows if r.transaction_type == "outflow")
    bear = sum(r.amount or 0.0 for r in rows if r.transaction_type == "inflow")
    net = bull - bear
    s = max(-1.0, min(1.0, net / scale)) if scale else 0.0
    direction = "bullish" if net > 0 else "bearish" if net < 0 else "none"
    return {"role": "direction", "direction": direction, "conviction": round(abs(s), 4)}


def _sentiment_reading(asset, db, cfg, now):
    if not _enabled(cfg):
        return None
    cutoff = now - datetime.timedelta(seconds=_freshness(cfg, 86400))
    row = (
        db.query(SentimentScore)
        .filter(SentimentScore.asset == asset, SentimentScore.timestamp >= cutoff)
        .order_by(SentimentScore.timestamp.desc())
        .first()
    )
    if row is None:
        return None
    s = row.score if row.score is not None else 0.5
    direction = "bullish" if s > 0.5 else "bearish" if s < 0.5 else "none"
    return {"role": "confirm", "direction": direction, "conviction": round(abs(s - 0.5) * 2, 4)}


def _institutional_reading(asset, db, cfg, now):
    if not _enabled(cfg):
        return None
    rows = (
        db.query(InstitutionalPosition)
        .filter(InstitutionalPosition.ticker == asset)
        .all()
    )
    if not rows:
        return None
    funds_held = {r.fund_name for r in rows}
    total = len((cfg.options or {}).get("funds", [])) or len(funds_held)
    score = len(funds_held) / total if total else 0.0
    return {"role": "support", "direction": "bullish", "conviction": round(score, 4)}


# --- combine ----------------------------------------------------------------

def fuse_asset(asset, db: Session, now=None):
    now = now or datetime.datetime.utcnow()

    tech = _technical_reading(asset, db, _cfg(db, "technical"), now)
    sent = _sentiment_reading(asset, db, _cfg(db, "sentiment"), now)
    inst = _institutional_reading(asset, db, _cfg(db, "institutional"), now)
    if is_crypto(asset):
        direction_src = _whale_reading(asset, db, _cfg(db, "whale"), now)
        whale_is_dir = True
    else:
        direction_src = _insider_reading(asset, db, _cfg(db, "insider"), now)
        whale_is_dir = False

    fcfg = _cfg(db, "fusion")
    fopts = (fcfg.options if fcfg and fcfg.options else None) or DEFAULTS
    arm_threshold = fopts.get("arm_threshold", DEFAULTS["arm_threshold"])
    w_dir = fopts.get("w_direction", DEFAULTS["w_direction"])
    w_sent = fopts.get("w_sentiment", DEFAULTS["w_sentiment"])
    w_sup = fopts.get("w_support", DEFAULTS["w_support"])

    direction = direction_src["direction"] if direction_src else "none"

    def agrees(r):
        return bool(r and direction != "none" and r["direction"] == direction)

    technical_conf = agrees(tech)
    sentiment_conf = agrees(sent)
    institutional_conf = agrees(inst)
    whale_conf = bool(whale_is_dir and direction != "none")

    # Confidence: direction conviction gated by timing, nudged by confirm/support.
    timing_strength = tech["strength"] if technical_conf else 0.0
    direction_conviction = direction_src["conviction"] if direction_src else 0.0
    c = w_dir * direction_conviction * timing_strength
    if sent:
        c += w_sent * sent["conviction"] * (1 if sentiment_conf else -1)
    if institutional_conf:
        c += w_sup * inst["conviction"]
    confidence = round(max(0.0, min(1.0, c)), 4)

    # Hard gate: direction present AND technical agrees AND confidence clears bar.
    armed = direction != "none" and technical_conf and confidence >= arm_threshold
    status = "pending" if armed else "watch"
    signal_type = "buy" if direction == "bullish" else "sell" if direction == "bearish" else None

    reasoning = None
    if armed:
        # Only ever called on armed rows — never on watch rows.
        from app.services.reasoning import generate_reasoning
        detail = (
            f"direction conviction {direction_conviction:.2f}, "
            f"technical timing {timing_strength:.2f}"
        )
        reasoning = generate_reasoning({
            "asset": asset,
            "direction": direction,
            "confidence": confidence,
            "technical_conf": technical_conf,
            "sentiment_conf": sentiment_conf,
            "institutional_conf": institutional_conf,
            "whale_conf": whale_conf,
            "detail": detail,
        }, db)

    row = TradingSignal(
        asset=asset,
        direction=direction,
        signal_type=signal_type,
        confidence_score=confidence,
        status=status,
        institutional_conf=institutional_conf,
        whale_conf=whale_conf,
        technical_conf=technical_conf,
        sentiment_conf=sentiment_conf,
        reasoning=reasoning,
        timestamp=now,
    )
    db.add(row)
    db.commit()
    return row


def run_fusion(assets, db: Session):
    now = datetime.datetime.utcnow()
    return [fuse_asset(asset, db, now=now) for asset in assets]
