import datetime

import pandas as pd
import pandas_ta_classic as ta
from sqlalchemy.orm import Session

from app.models.models import TechnicalSignal, SourceConfig
from app.services.market_data import get_ohlcv
from app.services import assets


def _rsi_signal(last):
    val = last["RSI_14"]
    if pd.isna(val):
        return None
    if val < 30:
        sig = "buy"
    elif val > 70:
        sig = "sell"
    else:
        sig = "neutral"
    return ("RSI", float(val), sig)


def _macd_signal(df):
    # Crossover of the MACD line vs its signal line, read across the last two bars.
    if len(df) < 2:
        return None
    prev, last = df.iloc[-2], df.iloc[-1]
    m_prev, s_prev = prev["MACD_12_26_9"], prev["MACDs_12_26_9"]
    m_last, s_last = last["MACD_12_26_9"], last["MACDs_12_26_9"]
    hist = last["MACDh_12_26_9"]
    if any(pd.isna(x) for x in (m_prev, s_prev, m_last, s_last, hist)):
        return None
    if m_prev <= s_prev and m_last > s_last:
        sig = "buy"
    elif m_prev >= s_prev and m_last < s_last:
        sig = "sell"
    else:
        sig = "neutral"
    return ("MACD", float(hist), sig)


def _ma_cross_signal(last):
    # SMA20 vs SMA50 trend regime (fast above slow = uptrend).
    fast, slow = last["SMA_20"], last["SMA_50"]
    if pd.isna(fast) or pd.isna(slow):
        return None
    if fast > slow:
        sig = "buy"
    elif fast < slow:
        sig = "sell"
    else:
        sig = "neutral"
    return ("MA_CROSS", float(fast - slow), sig)


def _support_resistance_signal(last):
    # Donchian channel as support/resistance; value is position in the channel (0=support, 1=resistance).
    support, resistance, close = last["DCL_20_20"], last["DCU_20_20"], last["Close"]
    if pd.isna(support) or pd.isna(resistance) or resistance == support:
        return None
    position = (close - support) / (resistance - support)
    if position >= 0.98:
        sig = "buy"
    elif position <= 0.02:
        sig = "sell"
    else:
        sig = "neutral"
    return ("SUPPORT_RESISTANCE", float(position), sig)


def fetch_and_analyze(ticker: str, db: Session):
    # Read the technical source's provider choice at runtime — switching needs no redeploy.
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "technical").first()
    if cfg is not None and not cfg.enabled:
        return []
    exchange = cfg.provider if cfg is not None else None
    options = cfg.options if cfg is not None and cfg.options else {}

    data = get_ohlcv(
        ticker,
        asset_type=assets.type_of(ticker, db),
        exchange=exchange,
        timeframe=options.get("timeframe", "1h"),
        limit=options.get("limit", 300),
    )
    if data is None or data.empty:
        return []

    data.ta.rsi(append=True)
    data.ta.macd(append=True)
    data.ta.sma(length=20, append=True)
    data.ta.sma(length=50, append=True)
    data.ta.donchian(lower_length=20, upper_length=20, append=True)

    last_row = data.iloc[-1]
    now = datetime.datetime.utcnow()

    readings = [
        _rsi_signal(last_row),
        _macd_signal(data),
        _ma_cross_signal(last_row),
        _support_resistance_signal(last_row),
    ]

    written = []
    for reading in readings:
        if reading is None:
            continue
        name, value, signal_type = reading
        signal = TechnicalSignal(
            asset=ticker,
            indicator_name=name,
            value=value,
            signal_type=signal_type,
            timestamp=now,
        )
        db.add(signal)
        written.append(signal)

    db.commit()
    return written
