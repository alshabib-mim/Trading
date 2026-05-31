"""Asset universe — the single source of truth for which symbols are tracked
and each symbol's type (stock | crypto). Read from asset_config at runtime so
adding/removing an asset in the UI takes effect on the next scheduler tick with
no redeploy (same live-switching as source_config).

asset_type drives everything downstream: which OHLCV source (ccxt vs yfinance),
which adapters run (insider/13F/sentiment = stocks; whale = crypto), and which
direction source fusion uses (insider for stocks, whale for crypto).
"""
from sqlalchemy.orm import Session

from app.models.models import AssetConfig

# Last-resort fallback only (used if the table is empty). NOT the source of
# truth — real types come from asset_config.
_FALLBACK = [
    ("AAPL", "stock"), ("MSFT", "stock"), ("NVDA", "stock"), ("AMZN", "stock"),
    ("GOOGL", "stock"), ("META", "stock"), ("TSLA", "stock"), ("OXY", "stock"),
    ("BTC-USD", "crypto"), ("ETH-USD", "crypto"), ("SOL-USD", "crypto"),
]


def enabled_assets(db: Session):
    """[(symbol, asset_type)] for enabled assets, ordered by symbol."""
    rows = (
        db.query(AssetConfig)
        .filter(AssetConfig.enabled == True)  # noqa: E712
        .order_by(AssetConfig.symbol)
        .all()
    )
    if not rows:
        return list(_FALLBACK)
    return [(r.symbol, r.asset_type) for r in rows]


def enabled_symbols(db: Session):
    return [s for s, _ in enabled_assets(db)]


def split(db: Session):
    """(stock_symbols, crypto_symbols) for enabled assets."""
    ea = enabled_assets(db)
    stocks = [s for s, t in ea if t == "stock"]
    crypto = [s for s, t in ea if t == "crypto"]
    return stocks, crypto


def type_of(symbol: str, db: Session):
    """Resolve a symbol's type from config; heuristic fallback if unknown
    (anything ending -USD is treated as crypto)."""
    row = db.query(AssetConfig).filter(AssetConfig.symbol == symbol).first()
    if row is not None:
        return row.asset_type
    return "crypto" if symbol.upper().endswith("-USD") else "stock"


def is_crypto(symbol: str, db: Session):
    return type_of(symbol, db) == "crypto"
