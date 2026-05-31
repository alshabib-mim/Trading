"""SEC EDGAR adapter — free, unrestricted. Currently serves Form 4 (insider
transactions, fast → stock DIRECTION). The 13F support feed will be added here
as a second function in a later pass.

SEC fair-access policy requires a real User-Agent contact string on every
request and caps traffic at ~10 req/s. No API key is needed.
"""
import os
import re
import time
import datetime
import xml.etree.ElementTree as ET

import requests
from sqlalchemy.orm import Session

from app.models.models import InsiderTransaction, InstitutionalPosition, SourceConfig
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


# ---------------------------------------------------------------------------
# 13F support feed (slow, SUPPORT-only). Confirms that tracked "smart money"
# funds hold a name the faster signals already flagged — never arms alone.
# 13F reports CUSIP + nameOfIssuer (no ticker), so we map nameOfIssuer to a
# ticker by normalized-name match against EDGAR's company-title list. Good
# enough for a support nudge; not a precise CUSIP map.
# ---------------------------------------------------------------------------

_NAME_SUFFIXES = {
    "INC", "CORP", "CORPORATION", "CO", "COMPANY", "LP", "LLP", "LLC", "LTD",
    "PLC", "THE", "COM", "CL", "CLASS", "HLDGS", "HOLDINGS", "HOLDING", "GROUP",
    "GRP", "SA", "NV", "AG", "TRUST", "ADR", "PLC.", "&",
}
_company_titles = {}  # ticker -> normalized title


def _norm_name(s):
    s = re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())
    toks = [t for t in s.split() if t and t not in _NAME_SUFFIXES]
    return " ".join(toks)


def _load_company_titles():
    if _company_titles:
        return _company_titles
    data = _get(_TICKER_MAP_URL, as_json=True)
    for row in data.values():
        _company_titles[row["ticker"].upper()] = _norm_name(row["title"])
    return _company_titles


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _latest_13f(cik):
    data = _get(_SUBMISSIONS_URL.format(cik=cik), as_json=True)
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accnos = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    for i, form in enumerate(forms):
        if form == "13F-HR":
            return {"accession": accnos[i], "filed": dates[i]}
    return None


def _info_table_url(cik, accession):
    acc = accession.replace("-", "")
    idx = _get(f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json", as_json=True)
    items = idx.get("directory", {}).get("item", [])
    xmls = [it["name"] for it in items if it["name"].lower().endswith(".xml")]
    # Prefer a filename that looks like the information table; skip the cover doc.
    for nm in xmls:
        low = nm.lower()
        if "primary_doc" in low:
            continue
        if any(k in low for k in ("infotable", "form13f", "table", "info")):
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{nm}"
    for nm in xmls:
        if "primary_doc" not in nm.lower():
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{nm}"
    return None


def _parse_info_table(xml_bytes):
    root = ET.fromstring(xml_bytes)
    holdings = []
    for el in root.iter():
        if _local(el.tag) != "infoTable":
            continue
        h = {"name": None, "cusip": None, "value": 0.0, "shares": 0.0}
        for child in el:
            lt = _local(child.tag)
            if lt == "nameOfIssuer":
                h["name"] = (child.text or "").strip()
            elif lt == "cusip":
                h["cusip"] = (child.text or "").strip()
            elif lt == "value":
                try:
                    h["value"] = float(child.text)
                except (TypeError, ValueError):
                    pass
            elif lt == "shrsOrPrnAmt":
                for gc in child:
                    if _local(gc.tag) == "sshPrnamt":
                        try:
                            h["shares"] = float(gc.text)
                        except (TypeError, ValueError):
                            pass
        if h["name"]:
            holdings.append(h)
    return holdings


def _fund_list(cfg):
    funds = (cfg.options or {}).get("funds", []) or []
    out = []
    for f in funds:
        if isinstance(f, dict) and f.get("cik"):
            out.append((str(f["cik"]), f.get("name", "")))
        elif f:
            out.append((str(f), ""))
    return out


def fetch_13f_readings(tickers, db: Session, cfg: SourceConfig):
    """SUPPORT readings: for each tracked stock ticker, how many tracked funds
    hold it in their latest 13F. Persists holdings to institutional_positions.
    """
    fund_list = _fund_list(cfg)
    if not fund_list:
        return []

    stock_tickers = [t for t in tickers if not is_crypto(t)]
    titles = _load_company_titles()
    title_to_ticker = {}
    for t in stock_tickers:
        norm = titles.get(t.upper())
        if norm:
            title_to_ticker[norm] = t

    agg = {t: {"funds": set(), "value": 0.0, "rows": []} for t in stock_tickers}
    for cik, fname in fund_list:
        latest = _latest_13f(cik)
        if not latest:
            continue
        url = _info_table_url(cik, latest["accession"])
        if not url:
            continue
        try:
            holdings = _parse_info_table(_get(url))
        except (requests.RequestException, ET.ParseError):
            continue
        label = fname or cik
        for h in holdings:
            tk = title_to_ticker.get(_norm_name(h["name"]))
            if tk is None:
                continue
            agg[tk]["funds"].add(label)
            agg[tk]["value"] += h["value"]
            agg[tk]["rows"].append((label, tk, h["shares"], h["value"], latest["filed"]))

    total_funds = len(fund_list)
    readings = []
    for tk, a in agg.items():
        n = len(a["funds"])
        if n == 0:
            continue
        for (fn, t, shares, value, filed) in a["rows"]:
            db.add(InstitutionalPosition(
                fund_name=fn, ticker=t, shares=shares, value=value,
                conviction_score=0.0, quarter=filed,
            ))
        readings.append({
            "source": "institutional",
            "asset": tk,
            "direction": "bullish",          # held by funds = bullish tilt...
            "score": round(n / total_funds, 4),
            "role": "support",               # ...but SUPPORT only — never arms alone
            "detail": f"{n}/{total_funds} tracked funds hold {tk}",
            "observed_at": datetime.datetime.utcnow().isoformat(),
        })
    db.commit()
    return readings


def run_13f(tickers, db: Session):
    cfg = db.query(SourceConfig).filter(SourceConfig.source == "institutional").first()
    if cfg is None or not cfg.enabled:
        return []
    try:
        return fetch_13f_readings(tickers, db, cfg)
    except requests.RequestException:
        return []
