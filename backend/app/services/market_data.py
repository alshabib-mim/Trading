import os

import ccxt
import pandas as pd
import yfinance as yf

# Assets fetched from a crypto exchange via ccxt rather than yfinance.
CRYPTO_ASSETS = {"BTC-USD", "ETH-USD"}
CCXT_EXCHANGE = os.getenv("CCXT_EXCHANGE", "kraken")

_exchange = None


def is_crypto(asset: str) -> bool:
    return asset in CRYPTO_ASSETS


def _get_exchange():
    global _exchange
    if _exchange is None:
        _exchange = getattr(ccxt, CCXT_EXCHANGE)({"enableRateLimit": True, "timeout": 15000})
    return _exchange


def _ccxt_symbol(asset: str) -> str:
    # "BTC-USD" -> "BTC/USD"
    return asset.replace("-", "/")


def _fetch_crypto_ohlcv(asset: str, timeframe: str = "1h", limit: int = 300) -> pd.DataFrame:
    raw = _get_exchange().fetch_ohlcv(_ccxt_symbol(asset), timeframe=timeframe, limit=limit)
    if not raw:
        return pd.DataFrame()
    df = pd.DataFrame(raw, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.drop(columns=["ts"])


def _fetch_stock_ohlcv(asset: str, period: str = "1mo", interval: str = "1h") -> pd.DataFrame:
    data = yf.download(asset, period=period, interval=interval, progress=False)
    if data.empty:
        return data
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def get_ohlcv(asset: str) -> pd.DataFrame:
    """OHLCV DataFrame with Open/High/Low/Close/Volume columns, crypto via ccxt, stocks via yfinance."""
    if is_crypto(asset):
        return _fetch_crypto_ohlcv(asset)
    return _fetch_stock_ohlcv(asset)
