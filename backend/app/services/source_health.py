"""Per-source run health — distinct from the data-write timestamp.

A single wrapper classifies each source job's run into three states WITHOUT
touching the adapters (table-delta): ok (wrote new/updated rows), no_data (ran
clean, nothing to write — HEALTHY), error (the run raised). Disabled sources are
skipped. Failures/recoveries edge-trigger the source_error Telegram alert.
"""
import logging
import datetime

from sqlalchemy import func

from app.models.models import (
    SourceHealth, SourceConfig, TechnicalSignal, WhaleMovement, InsiderTransaction,
    InstitutionalPosition, SentimentScore, MacroBias,
)

logger = logging.getLogger("source_health")

# source key -> (data model, timestamp column) used to detect "wrote data".
SOURCE_TABLES = {
    "technical": (TechnicalSignal, "timestamp"),
    "whale": (WhaleMovement, "timestamp"),
    "insider": (InsiderTransaction, "created_at"),
    "institutional": (InstitutionalPosition, "updated_at"),
    "sentiment": (SentimentScore, "timestamp"),
    "macro": (MacroBias, "timestamp"),
}


def _enabled(db, source_key):
    cfg = db.query(SourceConfig).filter(SourceConfig.source == source_key).first()
    return bool(cfg and cfg.enabled)


def _snapshot(db, source_key):
    """(row_count, max_timestamp) — counts inserts AND (via max) in-place updates
    like 13F's updated_at, so 'wrote data' is detected for both append and upsert."""
    model, col = SOURCE_TABLES[source_key]
    count = db.query(func.count(model.id)).scalar() or 0
    mx = db.query(func.max(getattr(model, col))).scalar()
    return (count, mx.isoformat() if mx else None)


def record_run(db, source_key, started_at, state, message=None):
    """Persist the outcome + edge-trigger the source_error / recovery alert."""
    row = db.query(SourceHealth).filter(SourceHealth.source == source_key).first()
    if row is None:
        row = SourceHealth(source=source_key)
        db.add(row)
    prev = row.last_state
    now = datetime.datetime.utcnow()
    row.last_run_at = started_at
    row.last_state = state
    row.last_message = message if state == "error" else None
    if state == "ok":
        row.last_ok_at = now

    from app.services import alerts  # lazy import avoids a circular dependency
    if state == "error" and prev != "error":
        # healthy → failing: alert ONCE.
        row.failing_since = now
        row.alerted = True
        alerts.source_error(source_key, message, db)
    elif state != "error" and prev == "error":
        # failing → healthy: recovery note ONCE.
        alerts.source_recovered(source_key, db)
        row.failing_since = None
        row.alerted = False

    db.commit()
    return row


def run_with_health(db, source_key, fn):
    """Run a source job and record its outcome. Skips disabled sources (D4)."""
    if not _enabled(db, source_key):
        return None
    before = _snapshot(db, source_key)
    started = datetime.datetime.utcnow()
    try:
        fn()
        after = _snapshot(db, source_key)
        state = "ok" if after != before else "no_data"
        return record_run(db, source_key, started, state)
    except Exception as exc:  # noqa: BLE001 — the run failed; capture, don't propagate
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.exception("source %s run failed", source_key)
        return record_run(db, source_key, started, "error", str(exc)[:500])


def all_health(db):
    """{source: SourceHealth} for every recorded source."""
    return {r.source: r for r in db.query(SourceHealth).all()}
