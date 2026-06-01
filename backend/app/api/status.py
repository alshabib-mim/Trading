"""System status — per-source data freshness + next scheduled run, and market
open/close. Read at request time; cadence comes from each source's config, the
next run from the LIVE scheduler (interval sources) or run_times (macro), and
last-updated from each source's data table. Times are naive UTC; the client
renders them in the viewer's local zone.
"""
import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.models import (
    User, SourceConfig, TechnicalSignal, WhaleMovement, InsiderTransaction,
    InstitutionalPosition, SentimentScore, MacroBias,
)
from app.services import macro, market_hours, source_health
from app.tasks import scheduler

router = APIRouter()

# source key -> (display label, data model, timestamp column, scheduler job id)
SOURCES = [
    ("technical", "Technical", TechnicalSignal, "timestamp", "technical"),
    ("whale", "Whale flow", WhaleMovement, "timestamp", "whale"),
    ("insider", "Insider (Form 4)", InsiderTransaction, "created_at", "insider"),
    ("institutional", "13F", InstitutionalPosition, "updated_at", "institutional"),
    ("sentiment", "Sentiment", SentimentScore, "timestamp", "sentiment"),
    ("macro", "Macro news", MacroBias, "timestamp", None),  # next via run_times, not the tick
]


def _cadence(interval_seconds):
    if not interval_seconds:
        return "—"
    if interval_seconds % 3600 == 0:
        h = interval_seconds // 3600
        return "hourly" if h == 1 else f"every {h} hours"
    if interval_seconds % 60 == 0:
        return f"every {interval_seconds // 60} min"
    return f"every {interval_seconds}s"


def _macro_cadence(cfg):
    rts = (cfg.options or {}).get("run_times") if cfg else None
    rts = rts or ["13:00"]
    if len(rts) == 1:
        return f"daily at {rts[0]} UTC"
    return "twice daily (" + ", ".join(rts) + " UTC)"


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() if dt else None


@router.get("/")
def get_status(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    cfgs = {c.source: c for c in db.query(SourceConfig).all()}
    health = source_health.all_health(db)
    out = []
    for key, label, model, col, job in SOURCES:
        cfg = cfgs.get(key)
        last = db.query(func.max(getattr(model, col))).scalar()
        if key == "macro":
            cadence = _macro_cadence(cfg)
            next_run = macro.next_fetch_at(cfg)
        else:
            cadence = _cadence(cfg.interval_seconds if cfg else None)
            next_run = scheduler.next_run_for(job)
        h = health.get(key)
        out.append({
            "key": key,
            "label": label,
            "enabled": bool(cfg.enabled) if cfg else False,
            "cadence": cadence,
            "last_updated": _iso(last),
            "next_run": _iso(next_run),
            # Health: state ok|no_data|error (None = never run / disabled).
            "health": {
                "state": h.last_state if h else None,
                "last_run_at": _iso(h.last_run_at) if h else None,
                "message": h.last_message if (h and h.last_state == "error") else None,
                "failing_since": _iso(h.failing_since) if (h and h.failing_since) else None,
            },
        })

    return {
        "now": _iso(datetime.datetime.utcnow()),
        "markets": market_hours.all_markets(),
        "sources": out,
    }
