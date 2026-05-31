import yfinance as yf
import pandas_ta as ta
import pandas as pd
from sqlalchemy.orm import Session
from app.models.models import TechnicalSignal
import datetime

def fetch_and_analyze(ticker: str, db: Session):
    data = yf.download(ticker, period="1mo", interval="1h")
    if data.empty:
        return
    
    # Flatten MultiIndex columns if present
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    
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
