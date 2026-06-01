import datetime
import logging
from datetime import timezone

from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.tasks import schedules
from app.services.technical_analysis import fetch_and_analyze
from app.services.edgar import run_insider, run_13f
from app.services.whale import run_whale
from app.services.fusion import run_fusion
from app.services.risk import run_risk_engine
from app.services.news import run_sentiment
from app.services.macro import run_macro
from app.services.maintenance import cleanup_watch_rows
from app.services import assets, source_health

_log = logging.getLogger("scheduler")


def _run_technical(db):
    """Per-symbol resilient (D2): one flaky symbol (e.g. yfinance hiccup) does NOT
    fail the source — it stays healthy. Only a SYSTEMIC failure (every symbol
    failed) raises and is recorded as 'error'."""
    symbols = assets.enabled_symbols(db)
    errors = []
    for symbol in symbols:
        try:
            fetch_and_analyze(symbol, db)
        except Exception as exc:  # noqa: BLE001 — isolate per-symbol failures
            errors.append(f"{symbol}: {exc}")
            _log.warning("technical: %s failed: %s", symbol, exc)
    if symbols and len(errors) == len(symbols):
        raise RuntimeError(f"all {len(symbols)} symbols failed (e.g. {errors[0]})")


def update_technical_signals():
    db = SessionLocal()
    try:
        source_health.run_with_health(db, "technical", lambda: _run_technical(db))
    finally:
        db.close()


def update_insider_signals():
    # Stocks only (Form 4 is equities). No-op unless the 'insider' source is enabled.
    db = SessionLocal()
    try:
        stocks, _ = assets.split(db)
        source_health.run_with_health(db, "insider", lambda: run_insider(stocks, db))
    finally:
        db.close()


def update_whale_signals():
    # Crypto only. No-op unless the 'whale' source is enabled with a credential.
    db = SessionLocal()
    try:
        _, crypto = assets.split(db)
        source_health.run_with_health(db, "whale", lambda: run_whale(crypto, db))
    finally:
        db.close()


def update_institutional_signals():
    # Stocks only (13F support). No-op unless the 'institutional' source is enabled.
    db = SessionLocal()
    try:
        stocks, _ = assets.split(db)
        source_health.run_with_health(db, "institutional", lambda: run_13f(stocks, db))
    finally:
        db.close()


def update_sentiment_signals():
    # Stocks only (Finnhub equities). No-op until 'news' (key) + 'sentiment' enabled.
    db = SessionLocal()
    try:
        stocks, _ = assets.split(db)
        source_health.run_with_health(db, "sentiment", lambda: run_sentiment(stocks, db))
    finally:
        db.close()


def update_macro_signals():
    # Forex macro news (4th source). Frequent TICK — run_macro internally decides
    # whether it's actually due: enabled + forex market open (skips the Fri→Sun
    # weekend) + a new scheduled run-time slot (once/twice daily, UI-tunable). So
    # cadence/time/enabled changes in Config take effect with no redeploy, and the
    # expensive web_search fetch fires at most once per slot.
    db = SessionLocal()
    try:
        # Health for macro reflects the gate tick: 'no_data' between daily slots
        # (ran, not due), 'ok' when it fetches, 'error' if the web_search call raises.
        source_health.run_with_health(db, "macro", lambda: run_macro(db))
    finally:
        db.close()


def update_fused_signals():
    # Combine the freshest source readings into trading_signals (watch/pending).
    db = SessionLocal()
    try:
        run_fusion(assets.enabled_symbols(db), db)
    finally:
        db.close()


def update_risk_engine():
    # Paper execution + risk controls: open/manage/close positions, enforce breakers.
    db = SessionLocal()
    try:
        run_risk_engine(db)
    finally:
        db.close()


def cleanup_old_watch_rows():
    db = SessionLocal()
    try:
        cleanup_watch_rows(db)
    finally:
        db.close()


# Live scheduler handle so the status endpoint can read each job's REAL next run
# time (the actual schedule, not an estimate). Set on start_scheduler().
_scheduler = None

# job id -> function (cron schedules live in schedules.CRON, on fixed UTC boundaries).
JOBS = {
    "technical": update_technical_signals,
    "whale": update_whale_signals,
    "macro": update_macro_signals,
    "fusion": update_fused_signals,
    "risk": update_risk_engine,
    "sentiment": update_sentiment_signals,
    "insider": update_insider_signals,
    "institutional": update_institutional_signals,
    "cleanup": cleanup_old_watch_rows,
}


def start_scheduler():
    # tz=UTC so cron fields are fixed UTC boundaries (deploy-independent).
    scheduler = BackgroundScheduler(timezone="UTC")
    for job_id, fn in JOBS.items():
        scheduler.add_job(fn, 'cron', id=job_id, replace_existing=True, **schedules.CRON[job_id])
    scheduler.start()

    # Run-on-startup for the FREE source(s) only — refresh immediately after a deploy
    # without waiting for the next boundary. One-shot 'date' job a few seconds out so
    # it runs in a worker thread instead of blocking app startup.
    for job_id in schedules.RUN_ON_STARTUP:
        scheduler.add_job(
            JOBS[job_id], 'date',
            run_date=datetime.datetime.now(timezone.utc) + datetime.timedelta(seconds=5),
            id=f"{job_id}_startup", replace_existing=True,
        )

    global _scheduler
    _scheduler = scheduler
    return scheduler


def next_run_for(job_id):
    """The job's real next run time as a naive UTC datetime, or None. The macro
    job is a 15-min gate tick — its meaningful next fetch is computed from
    run_times in macro.next_fetch_at, not from this tick."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(job_id)
    if job is None or job.next_run_time is None:
        return None
    dt = job.next_run_time
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt
