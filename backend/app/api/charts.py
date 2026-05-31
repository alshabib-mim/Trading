"""Chart data — the exact OHLCV + indicators the engine analyzes.

Reuses the same pipeline as technical_analysis.py (get_ohlcv + pandas-ta:
RSI_14, MACD_12_26_9, SMA_20/50, Donchian 20/20) so the chart shows literally
what the system sees, plus Fibonacci retracement levels over the window.
"""
import datetime
import math

import pandas as pd
import pandas_ta_classic as ta  # noqa: F401 (registers the .ta accessor)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.deps import get_current_user
from app.models.models import User, SourceConfig
from app.services.market_data import get_ohlcv
from app.services import assets, twelvedata

router = APIRouter()

# Coattails default: 1h candles, ~30 days of history (sustained-wave context).
DEFAULT_TIMEFRAME = "1h"
DEFAULT_LIMIT = 720
MAX_LIMIT = 1500

# 0% = swing low, 100% = swing high (uptrend retracement framing).
FIB_RATIOS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]


def _epoch(ts):
    return int(pd.Timestamp(ts).timestamp())


def _clean(value):
    if value is None:
        return None
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _series(index, column):
    out = []
    for t, v in zip(index, column):
        cv = _clean(v)
        if cv is None:
            continue
        out.append({"time": _epoch(t), "value": round(cv, 6)})
    return out


def _col(data, name):
    if name in data.columns:
        return data[name]
    return pd.Series([float("nan")] * len(data), index=data.index)


@router.get("/{asset}")
def get_chart(
    asset: str,
    timeframe: str = DEFAULT_TIMEFRAME,
    limit: int = DEFAULT_LIMIT,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    limit = max(60, min(limit, MAX_LIMIT))

    cfg = db.query(SourceConfig).filter(SourceConfig.source == "technical").first()
    exchange = cfg.provider if cfg is not None else None
    asset_type = assets.type_of(asset, db)
    crypto = asset_type == "crypto"

    try:
        data = get_ohlcv(
            asset, asset_type=asset_type, exchange=exchange, timeframe=timeframe, limit=limit,
            api_key=twelvedata.get_key(db) if asset_type == "forex" else None,
        )
    except Exception as exc:  # noqa: BLE001 — surface upstream fetch errors cleanly
        raise HTTPException(status_code=502, detail=f"Market data error: {exc}")

    if data is None or data.empty:
        raise HTTPException(status_code=404, detail="No market data for asset")

    data.ta.rsi(append=True)
    data.ta.macd(append=True)
    data.ta.sma(length=20, append=True)
    data.ta.sma(length=50, append=True)
    data.ta.donchian(lower_length=20, upper_length=20, append=True)

    idx = data.index
    candles = []
    for t, row in data.iterrows():
        o, h, l, c = _clean(row["Open"]), _clean(row["High"]), _clean(row["Low"]), _clean(row["Close"])
        if None in (o, h, l, c):
            continue
        candles.append({
            "time": _epoch(t),
            "open": round(o, 6), "high": round(h, 6),
            "low": round(l, 6), "close": round(c, 6),
            "volume": round(_clean(row.get("Volume", 0)) or 0.0, 4),
        })

    indicators = {
        "sma20": _series(idx, _col(data, "SMA_20")),
        "sma50": _series(idx, _col(data, "SMA_50")),
        "donchian_upper": _series(idx, _col(data, "DCU_20_20")),
        "donchian_mid": _series(idx, _col(data, "DCM_20_20")),
        "donchian_lower": _series(idx, _col(data, "DCL_20_20")),
        "rsi": _series(idx, _col(data, "RSI_14")),
        "macd": _series(idx, _col(data, "MACD_12_26_9")),
        "macd_signal": _series(idx, _col(data, "MACDs_12_26_9")),
        "macd_hist": _series(idx, _col(data, "MACDh_12_26_9")),
    }

    hi = float(data["High"].max())
    lo = float(data["Low"].min())
    rng = hi - lo
    fib_levels = [
        {"ratio": r, "label": f"{r * 100:.1f}%", "price": round(lo + rng * r, 6)}
        for r in FIB_RATIOS
    ]

    last = candles[-1] if candles else None
    return {
        "asset": asset,
        "timeframe": timeframe,
        "exchange": exchange if crypto else ("twelvedata" if asset_type == "forex" else "yfinance"),
        "is_crypto": crypto,
        "candles": candles,
        "indicators": indicators,
        "fib": {"high": round(hi, 6), "low": round(lo, 6), "levels": fib_levels},
        "last_close": last["close"] if last else None,
        "last_time": last["time"] if last else None,
        "generated_at": datetime.datetime.utcnow().isoformat(),
    }
