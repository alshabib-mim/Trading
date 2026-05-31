"""SEC EDGAR adapter — free, unrestricted. Currently serves Form 4 (insider
transactions, fast → stock DIRECTION). The 13F support feed will be added here
as a second function in a later pass.

SEC fair-access policy requires a real User-Agent contact string on every
request and caps traffic at ~10 req/s. No API key is needed.
"""
import os
import time
import datetime
import xml.etree.ElementTree as ET

import requests
from sqlalchemy.orm import Session

from app.models.models import InsiderTransaction, SourceConfig
from app.services.market_data import is_crypto

SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "Mimar Trading System alshabib@mimarencasa.com")
_HEADERS = {"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}

_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

_RATE_DELAY = 0.2  # keep well under the 10 req/s ceiling
_cik_cache = {}


def _get(url, as_json=False):
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    time.sleep(_RATE_DELAY)
    resp.raise_for_status()
    return resp.json() if as_json else resp.content


def _load_cik_map():
    if _cik_cache:
        return _cik_cache
    data = _get(_TICKER_MAP_URL, as_json=True)
    for row in data.values():
        _cik_cache[row["ticker"].upper()] = int(row["cik_str"])
    return _cik_cache


def _ticker_to_cik(ticker):
    return _load_cik_map().get(ticker.upper())


def _recent_form4_filings(cik, lookback_days):
    data = _get(_SUBMISSIONS_URL.format(cik=cik), as_json=True)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accnos = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    dates = recent.get("filingDate", [])
    cutoff = datetime.date.today() - datetime.timedelta(days=lookback_days)
    out = []
    for i, form in enumerate(forms):
        if form != "4":
            continue
        try:
            filed = datetime.date.fromisoformat(dates[i])
        except (ValueError, IndexError):
            continue
        if filed < cutoff:
            continue
        out.append({"accession": accnos[i], "doc": docs[i], "filed": filed})
    return out


def _form4_xml_url(cik, accession, doc):
    acc = accession.replace("-", "")
    # primaryDocument is sometimes the xsl-rendered path ("xslF345X03/foo.xml");
    # the raw ownership XML lives at the same filename without that prefix.
    if doc.lower().startswith("xsl") and "/" in doc:
        doc = doc.split("/", 1)[1]
    return _ARCHIVE_BASE.format(cik=cik, acc=acc, doc=doc)


def _text(node, path):
    el = node.find(path)
    return el.text.strip() if el is not None and el.text else None


def _parse_form4(xml_bytes, codes):
    """Return a list of matching non-derivative transactions for one filing."""
    root = ET.fromstring(xml_bytes)
    owner = _text(root, "./reportingOwner/reportingOwnerId/rptOwnerName") or "UNKNOWN"
    txns = []
    for tx in root.findall("./nonDerivativeTable/nonDerivativeTransaction"):
        code = _text(tx, "./transactionCoding/transactionCode")
        if codes and code not in codes:
            continue
        shares = _text(tx, "./transactionAmounts/transactionShares/value")
        price = _text(tx, "./transactionAmounts/transactionPricePerShare/value")
        adcode = _text(tx, "./transactionAmounts/transactionAcquiredDisposedCode/value")
        date = _text(tx, "./transactionDate/value")
        try:
            shares_f = float(shares) if shares else 0.0
            price_f = float(price) if price else 0.0
        except ValueError:
            continue
        txns.append({
            "insider": owner,
            "code": code,
            "shares": shares_f,
            "price": price_f,
            "value": shares_f * price_f,
            "acquired": adcode,
            "date": date,
        })
    return txns


def fetch_form4_transactions(ticker, lookback_days=30, codes=("P",)):
    """All matching insider transactions for a ticker over the lookback window."""
    cik = _ticker_to_cik(ticker)
    if cik is None:
        return None, []
    collected = []
    for f in _recent_form4_filings(cik, lookback_days):
        url = _form4_xml_url(cik, f["accession"], f["doc"])
        try:
            for t in _parse_form4(_get(url), codes):
                t["accession"] = f["accession"]
                t["filed"] = f["filed"]
                collected.append(t)
        except (requests.RequestException, ET.ParseError):
            continue
    return cik, collected


def _score(transactions, opts):
    """Bullish-only feed (codes are filtered to open-market buys upstream).

    Strength rewards CLUSTER buying (multiple distinct insiders) more than a
    single large buy, plus a dollar-magnitude component. Both scales tunable
    via the source's options.
    """
    if not transactions:
        return "none", 0.0
    buyers = {t["insider"] for t in transactions}
    net_value = sum(t["value"] for t in transactions)
    buyer_scale = opts.get("buyer_scale", 3)
    value_scale = opts.get("value_scale", 500000)
    score = 0.6 * min(len(buyers) / buyer_scale, 1.0) + 0.4 * min(net_value / value_scale, 1.0)
    return "bullish", round(min(score, 1.0), 4)


def store_and_score(ticker, db: Session, cfg: SourceConfig):
    opts = cfg.options or {}
    codes = tuple(opts.get("transaction_codes", ["P"]))
    lookback = opts.get("lookback_days", 30)

    cik, txns = fetch_form4_transactions(ticker, lookback_days=lookback, codes=codes)

    # Dedupe across re-runs: skip any filing we've already stored for this ticker.
    existing = {
        r.accession
        for r in db.query(InsiderTransaction.accession)
        .filter(InsiderTransaction.ticker == ticker)
        .all()
    }
    stored = 0
    for t in txns:
        if t["accession"] in existing:
            continue
        db.add(InsiderTransaction(
            ticker=ticker,
            cik=str(cik),
            insider_name=t["insider"],
            transaction_code=t["code"],
            shares=t["shares"],
            price=t["price"],
            value=t["value"],
            transaction_date=t["date"],
            accession=t["accession"],
            filed_date=datetime.datetime.combine(t["filed"], datetime.time.min),
        ))
        stored += 1
    db.commit()

    direction, score = _score(txns, opts)
    buyers = {t["insider"] for t in txns}
    return {
        "source": "insider",
        "asset": ticker,
        "direction": direction,
        "score": score,
        "role": "direction",
        "detail": f"{len(buyers)} insider(s) buying, "
                  f"${sum(t['value'] for t in txns):,.0f} over {lookback}d",
        "stored": stored,
        "observed_at": datetime.datetime.utcnow().isoformat(),
    }


def run_insider(tickers, db: Session):
    """Scheduler entry point. No-op unless the 'insider' source is enabled.
    Crypto tickers are skipped — Form 4 is equities only.
    """
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "insider").first()
    if cfg is None or not cfg.enabled:
        return []
    readings = []
    for ticker in tickers:
        if is_crypto(ticker):
            continue
        try:
            readings.append(store_and_score(ticker, db, cfg))
        except requests.RequestException:
            continue
    return readings
