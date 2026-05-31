from apscheduler.schedulers.background import BackgroundScheduler
from app.db.session import SessionLocal
from app.services.technical_analysis import fetch_and_analyze

def update_technical_signals():
    db = SessionLocal()
    try:
        tickers = ["AAPL", "TSLA", "BTC-USD", "ETH-USD"]
        for ticker in tickers:
            fetch_and_analyze(ticker, db)
    finally:
        db.close()

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_technical_signals, 'interval', minutes=15)
    scheduler.start()
    return scheduler
