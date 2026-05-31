import os

import ccxt
import pandas as pd
import yfinance as yf

DEFAULT_EXCHANGE = os.getenv("CCXT_EXCHANGE", "kraken")

_exchanges = {}


def is_crypto(asset: str) -> bool:
    # Generic fallback heuristic only — the authoritative type comes from
    # asset_config (services/assets.py) and is passed to get_ohlcv explicitly.
    return asset.upper().endswith("-USD")


def _get_exchange(name: str):
    if name not in _exchanges:
        _exchanges[name] = getattr(ccxt, name)({"enableRateLimit": True, "timeout": 15000})
    return _exchanges[name]


def _ccxt_symbol(asset: str) -> str:
    # "BTC-USD" -> "BTC/USD"
    return asset.replace("-", "/")


def _fetch_crypto_ohlcv(asset: str, exchange: str, timeframe: str = "1h", limit: int = 300) -> pd.DataFrame:
    raw = _get_exchange(exchange).fetch_ohlcv(_ccxt_symbol(asset), timeframe=timeframe, limit=limit)
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


def get_ohlcv(asset: str, asset_type: str = None, exchange: str = None,
              timeframe: str = "1h", limit: int = 300, api_key: str = None) -> pd.DataFrame:
    """OHLCV DataFrame (Open/High/Low/Close/Volume): crypto via ccxt, stocks via
    yfinance, forex/gold via Twelve Data.

    `asset_type` ("stock"|"crypto"|"forex") selects the source — callers resolve
    it from asset_config. For crypto, `exchange` selects the ccxt exchange. For
    forex, `api_key` is the Twelve Data key (callers decrypt it from config); if
    absent, returns empty so nothing is fetched until the key is set.
    """
    if asset_type is None:
        asset_type = "crypto" if is_crypto(asset) else "stock"
    if asset_type == "crypto":
        return _fetch_crypto_ohlcv(asset, exchange or DEFAULT_EXCHANGE, timeframe=timeframe, limit=limit)
    if asset_type == "forex":
        from app.services.twelvedata import fetch_ohlcv
        return fetch_ohlcv(asset, api_key, timeframe=timeframe, outputsize=limit)
    return _fetch_stock_ohlcv(asset)
