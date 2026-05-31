from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.services.technical_analysis import fetch_and_analyze
from app.services.edgar import run_insider

TICKERS = ["AAPL", "TSLA", "BTC-USD", "ETH-USD"]


def update_technical_signals():
    db = SessionLocal()
    try:
        for ticker in TICKERS:
            fetch_and_analyze(ticker, db)
    finally:
        db.close()


def update_insider_signals():
    # No-op unless the 'insider' source is enabled in source_config;
    # run_insider skips crypto tickers (Form 4 is equities only).
    db = SessionLocal()
    try:
        run_insider(TICKERS, db)
    finally:
        db.close()


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_technical_signals, 'interval', minutes=15)
    scheduler.add_job(update_insider_signals, 'interval', hours=6)
    scheduler.start()
    return scheduler
