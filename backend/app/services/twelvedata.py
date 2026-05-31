"""Twelve Data adapter — OHLCV for forex pairs + gold (XAU/USD). Free tier.

Forex/gold is technical-only (no coattails data), so this just feeds the same
OHLCV shape the technical pipeline expects. API key is read (decrypted) from the
'forex' source config at runtime, like the other provider keys.

Symbols are stored dash-style (EUR-USD, USD-JPY, XAU-USD) for URL-safe routes
and converted to Twelve Data's slash form (EUR/USD) at the API boundary.
"""
import pandas as pd
import requests

from app.models.models import SourceConfig
from app.core.crypto import decrypt

_BASE = "https://api.twelvedata.com/time_series"


def _td_symbol(symbol: str) -> str:
    return symbol.replace("-", "/")


def get_key(db):
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "forex").first()
    if cfg is None or not cfg.enabled or not cfg.credentials_encrypted:
        return None
    return decrypt(cfg.credentials_encrypted)


def fetch_ohlcv(symbol: str, api_key: str, timeframe: str = "1h", outputsize: int = 300) -> pd.DataFrame:
    if not api_key:
        return pd.DataFrame()
    params = {
        "symbol": _td_symbol(symbol),
        "interval": timeframe,
        "outputsize": min(outputsize, 5000),
        "apikey": api_key,
        "format": "JSON",
    }
    resp = requests.get(_BASE, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "ok" or not data.get("values"):
        # Twelve Data returns {"status":"error","message":...} on failure.
        raise ValueError(data.get("message", "Twelve Data returned no data"))

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("datetime").set_index("datetime")
    vol = pd.to_numeric(df["volume"], errors="coerce") if "volume" in df.columns else 0.0
    return pd.DataFrame(
        {
            "Open": pd.to_numeric(df["open"], errors="coerce"),
            "High": pd.to_numeric(df["high"], errors="coerce"),
            "Low": pd.to_numeric(df["low"], errors="coerce"),
            "Close": pd.to_numeric(df["close"], errors="coerce"),
            "Volume": vol,
        },
        index=df.index,
    )
