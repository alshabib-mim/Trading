import pandas_ta_classic as ta
from sqlalchemy.orm import Session
from app.models.models import TechnicalSignal
from app.services.market_data import get_ohlcv
import datetime

def fetch_and_analyze(ticker: str, db: Session):
    data = get_ohlcv(ticker)
    if data is None or data.empty:
        return

    # Calculate indicators
    data.ta.rsi(append=True)
    data.ta.sma(length=20, append=True)
    data.ta.sma(length=50, append=True)
    
    last_row = data.iloc[-1]
    
    # Simple RSI strategy
    rsi_val = last_row['RSI_14']
    signal_type = "neutral"
    if rsi_val < 30:
        signal_type = "buy"
    elif rsi_val > 70:
        signal_type = "sell"
    
    signal = TechnicalSignal(
        asset=ticker,
        indicator_name="RSI",
        value=float(rsi_val),
        signal_type=signal_type,
        timestamp=datetime.datetime.utcnow()
    )
    db.add(signal)
    db.commit()
    return signal
