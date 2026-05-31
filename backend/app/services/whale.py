"""Whale Alert adapter — crypto DIRECTION from on-chain exchange flow.

Heuristic: large transfers LEAVING an exchange (to a private wallet) are
accumulation → bullish; large transfers ENTERING an exchange are potential
sell pressure → bearish. Net flow per asset gives direction + a normalized
0.0–1.0 score (0 = bearish, 0.5 = neutral, 1 = bullish).

The API key is read (decrypted) from the whale source config at runtime — the
first real use of the AES-256-GCM credential path. Build/backtest on the FREE
tier; the licensed quant tier is a later decision.
"""
import time
import datetime

import requests
from sqlalchemy.orm import Session

from app.models.models import WhaleMovement, SourceConfig
from app.core.crypto import decrypt

_BASE = "https://api.whale-alert.io/v1/transactions"

def _symbol(asset):
    # "BTC-USD" -> "btc", "SOL-USD" -> "sol" (Whale Alert currency code).
    if asset and asset.upper().endswith("-USD"):
        return asset.split("-")[0].lower()
    return None


def fetch_transactions(api_key, start_ts, min_value, currency=None):
    params = {"api_key": api_key, "start": start_ts, "min_value": min_value}
    if currency:
        params["currency"] = currency
    resp = requests.get(_BASE, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _classify(tx):
    f = (tx.get("from") or {}).get("owner_type")
    t = (tx.get("to") or {}).get("owner_type")
    if f == "exchange" and t != "exchange":
        return "outflow"   # leaving an exchange -> accumulation -> bullish
    if t == "exchange" and f != "exchange":
        return "inflow"    # entering an exchange -> sell pressure -> bearish
    return None            # exchange<->exchange or wallet<->wallet: ignore


def _score(net_usd, scale):
    if not scale:
        return 0.5
    s = max(-1.0, min(1.0, net_usd / scale))
    return round(0.5 + 0.5 * s, 4)


def store_and_score(asset, db: Session, cfg: SourceConfig, api_key: str):
    opts = cfg.options or {}
    min_value = opts.get("min_value", 500000)
    lookback = opts.get("lookback_seconds", 3600)
    scale = opts.get("scale", 50_000_000)

    currency = _symbol(asset)
    if currency is None:
        return None

    start_ts = int(time.time()) - lookback
    data = fetch_transactions(api_key, start_ts, min_value, currency=currency)
    txns = data.get("transactions") or []

    bullish_usd = 0.0
    bearish_usd = 0.0
    stored = 0
    for tx in txns:
        kind = _classify(tx)
        if kind is None:
            continue
        usd = float(tx.get("amount_usd") or 0.0)
        if kind == "outflow":
            bullish_usd += usd
        else:
            bearish_usd += usd
        db.add(WhaleMovement(
            asset=asset,
            amount=usd,
            transaction_type=kind,
            source="whale_alert",
            timestamp=datetime.datetime.utcfromtimestamp(tx.get("timestamp", time.time())),
        ))
        stored += 1
    db.commit()

    net = bullish_usd - bearish_usd
    score = _score(net, scale)
    direction = "bullish" if net > 0 else "bearish" if net < 0 else "none"
    return {
        "source": "whale",
        "asset": asset,
        "direction": direction,
        "score": score,
        "role": "direction",
        "detail": f"net ${net:,.0f} ({stored} flows: +${bullish_usd:,.0f} out / -${bearish_usd:,.0f} in)",
        "stored": stored,
        "observed_at": datetime.datetime.utcnow().isoformat(),
    }


def run_whale(assets, db: Session):
    """Scheduler entry point. No-op unless the 'whale' source is enabled and a
    credential is set. Non-crypto assets are skipped.
    """
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "whale").first()
    if cfg is None or not cfg.enabled:
        return []
    if not cfg.credentials_encrypted:
        return []
    api_key = decrypt(cfg.credentials_encrypted)

    readings = []
    for asset in assets:
        if _symbol(asset) is None:
            continue
        try:
            reading = store_and_score(asset, db, cfg, api_key)
            if reading:
                readings.append(reading)
        except requests.RequestException:
            continue
    return readings
