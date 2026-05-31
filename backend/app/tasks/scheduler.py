from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.services.technical_analysis import fetch_and_analyze
from app.services.edgar import run_insider, run_13f
from app.services.whale import run_whale
from app.services.fusion import run_fusion

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


def update_whale_signals():
    # No-op unless the 'whale' source is enabled and a credential is set;
    # run_whale skips non-crypto tickers.
    db = SessionLocal()
    try:
        run_whale(TICKERS, db)
    finally:
        db.close()


def update_institutional_signals():
    # No-op unless the 'institutional' (13F) source is enabled; support-only.
    db = SessionLocal()
    try:
        run_13f(TICKERS, db)
    finally:
        db.close()


def update_fused_signals():
    # Combine the freshest source readings into trading_signals (watch/pending).
    db = SessionLocal()
    try:
        run_fusion(TICKERS, db)
    finally:
        db.close()


def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_technical_signals, 'interval', minutes=15)
    scheduler.add_job(update_insider_signals, 'interval', hours=6)
    scheduler.add_job(update_whale_signals, 'interval', minutes=15)
    scheduler.add_job(update_institutional_signals, 'interval', hours=24)
    scheduler.add_job(update_fused_signals, 'interval', minutes=15)
    scheduler.start()
    return scheduler
