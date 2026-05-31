"""Housekeeping jobs. Watch-row retention: fusion writes a watch row per asset
every 15 min, so trading_signals grows unbounded. Trim watch rows older than
the retention window — but never delete the most-recent watch row per asset
(so the dashboard's current read survives even if fusion pauses), and never
touch pending/armed or any non-watch rows (those are the meaningful history).
"""
import os
import datetime

from sqlalchemy.orm import Session

from app.models.models import TradingSignal

RETENTION_DAYS = int(os.getenv("WATCH_RETENTION_DAYS", "7"))


def cleanup_watch_rows(db: Session, retention_days: int = None):
    retention_days = RETENTION_DAYS if retention_days is None else retention_days
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=retention_days)

    # Preserve the latest watch row per asset regardless of age.
    keep_ids = set()
    seen = set()
    for sid, asset in (
        db.query(TradingSignal.id, TradingSignal.asset)
        .filter(TradingSignal.status == "watch")
        .order_by(TradingSignal.timestamp.desc())
        .all()
    ):
        if asset not in seen:
            seen.add(asset)
            keep_ids.add(sid)

    q = db.query(TradingSignal).filter(
        TradingSignal.status == "watch",
        TradingSignal.timestamp < cutoff,
    )
    if keep_ids:
        q = q.filter(~TradingSignal.id.in_(keep_ids))
    deleted = q.delete(synchronize_session=False)
    db.commit()
    return deleted
