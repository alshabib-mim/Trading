from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.services.technical_analysis import fetch_and_analyze
from app.services.edgar import run_insider, run_13f
from app.services.whale import run_whale
from app.services.fusion import run_fusion
from app.services.risk import run_risk_engine
from app.services.news import run_sentiment
from app.services.macro import run_macro
from app.services.maintenance import cleanup_watch_rows
from app.services import assets


def update_technical_signals():
    db = SessionLocal()
    try:
        for symbol in assets.enabled_symbols(db):
            fetch_and_analyze(symbol, db)
    finally:
        db.close()


def update_insider_signals():
    # Stocks only (Form 4 is equities). No-op unless the 'insider' source is enabled.
    db = SessionLocal()
    try:
        stocks, _ = assets.split(db)
        run_insider(stocks, db)
    finally:
        db.close()


def update_whale_signals():
    # Crypto only. No-op unless the 'whale' source is enabled with a credential.
    db = SessionLocal()
    try:
        _, crypto = assets.split(db)
        run_whale(crypto, db)
    finally:
        db.close()


def update_institutional_signals():
    # Stocks only (13F support). No-op unless the 'institutional' source is enabled.
    db = SessionLocal()
    try:
        stocks, _ = assets.split(db)
        run_13f(stocks, db)
    finally:
        db.close()


def update_sentiment_signals():
    # Stocks only (Finnhub equities). No-op until 'news' (key) + 'sentiment' enabled.
    db = SessionLocal()
    try:
        stocks, _ = assets.split(db)
        run_sentiment(stocks, db)
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
        run_macro(db)
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


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_technical_signals, 'interval', minutes=15)
    scheduler.add_job(update_insider_signals, 'interval', hours=6)
    scheduler.add_job(update_whale_signals, 'interval', minutes=15)
    scheduler.add_job(update_institutional_signals, 'interval', hours=24)
    scheduler.add_job(update_sentiment_signals, 'interval', hours=1)
    scheduler.add_job(update_macro_signals, 'interval', minutes=15)
    scheduler.add_job(update_fused_signals, 'interval', minutes=15)
    scheduler.add_job(update_risk_engine, 'interval', minutes=5)
    scheduler.add_job(cleanup_old_watch_rows, 'interval', hours=24)
    scheduler.start()
    return scheduler
