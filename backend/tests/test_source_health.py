"""Per-source health + source_error alert tests.

MUST-PASS:
  (1) no_data NEVER alerts — a source that runs clean and writes nothing is HEALTHY.
  (2) the failure→recovery edge fires exactly once each, not repeatedly while broken.
Plus the synthetic forced-exception path producing the error state + Telegram alert.
"""
import os
import base64
import datetime

os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"0123456789abcdef0123456789abcdef").decode())

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, SourceConfig, AlertConfig, SourceHealth, WhaleMovement
from app.core.crypto import encrypt
from app.services import source_health, alerts


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    s = sessionmaker(bind=eng)()
    s.add(SourceConfig(source="whale", provider="whale_alert", enabled=True))
    s.commit()
    yield s
    s.close()


@pytest.fixture
def sent(monkeypatch):
    calls = []

    class _Resp:
        status_code = 200
        def json(self):
            return {"ok": True}

    monkeypatch.setattr(alerts.requests, "post",
                        lambda url, json=None, timeout=None: (calls.append(json) or _Resp()))
    return calls


def _enable_alerts(db):
    db.add(AlertConfig(channel="telegram", enabled=True,
                       bot_token_encrypted=encrypt("123:ABC"), chat_id_encrypted=encrypt("999"),
                       events=dict(alerts.DEFAULT_EVENTS)))
    db.commit()


def _write_whale(db):
    db.add(WhaleMovement(asset="BTC", amount=1.0, transaction_type="inflow", source="x",
                         timestamp=datetime.datetime.utcnow()))
    db.commit()


def _state(db):
    r = db.query(SourceHealth).filter(SourceHealth.source == "whale").first()
    return r


def _errors(sent):
    return [m for m in sent if "SOURCE ERROR" in m["text"]]


def _recoveries(sent):
    return [m for m in sent if "SOURCE RECOVERED" in m["text"]]


# ---- state classification --------------------------------------------------

def test_ok_when_wrote(db, sent):
    _enable_alerts(db)
    source_health.run_with_health(db, "whale", lambda: _write_whale(db))
    assert _state(db).last_state == "ok"
    assert _state(db).last_ok_at is not None
    assert sent == []  # success never alerts


def test_no_data_never_alerts(db, sent):
    """MUST-PASS (1): ran clean, wrote nothing → HEALTHY no_data, zero alerts."""
    _enable_alerts(db)
    source_health.run_with_health(db, "whale", lambda: None)      # writes nothing
    source_health.run_with_health(db, "whale", lambda: None)      # again
    h = _state(db)
    assert h.last_state == "no_data"
    assert h.failing_since is None
    assert h.alerted is False
    assert sent == []  # <-- the load-bearing assertion: no_data does NOT alert


def test_failure_recovery_edge_fires_once_each(db, sent):
    """MUST-PASS (2): one source_error on entering failure, one recovery on leaving —
    never repeated while it stays broken."""
    _enable_alerts(db)

    def boom():
        raise RuntimeError("Whale Alert 503")

    source_health.run_with_health(db, "whale", boom)   # healthy → error : alert #1
    source_health.run_with_health(db, "whale", boom)   # error → error  : silent
    source_health.run_with_health(db, "whale", boom)   # error → error  : silent
    assert len(_errors(sent)) == 1
    assert _state(db).last_state == "error" and _state(db).failing_since is not None

    source_health.run_with_health(db, "whale", lambda: _write_whale(db))  # error → ok : recovery #1
    source_health.run_with_health(db, "whale", lambda: None)              # ok → no_data : silent
    assert len(_errors(sent)) == 1          # still just the one failure alert
    assert len(_recoveries(sent)) == 1      # exactly one recovery
    assert _state(db).failing_since is None and _state(db).last_state == "no_data"


def test_error_message_in_alert(db, sent):
    _enable_alerts(db)
    source_health.run_with_health(db, "whale", lambda: (_ for _ in ()).throw(ValueError("boom-xyz")))
    assert _state(db).last_state == "error"
    assert "whale" in _errors(sent)[0]["text"] and "boom-xyz" in _errors(sent)[0]["text"]


def test_disabled_source_skipped(db, sent):
    db.query(SourceConfig).filter(SourceConfig.source == "whale").first().enabled = False
    db.commit()
    flag = {"ran": False}
    source_health.run_with_health(db, "whale", lambda: flag.__setitem__("ran", True))
    assert flag["ran"] is False           # fn never invoked
    assert _state(db) is None             # no health row recorded
    assert sent == []


def test_source_error_toggle_off_silences_both(db, sent):
    _enable_alerts(db)
    db.query(AlertConfig).first().events = {**alerts.DEFAULT_EVENTS, "source_error": False}
    db.commit()
    source_health.run_with_health(db, "whale", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert _state(db).last_state == "error"   # health still records
    assert sent == []                          # but no alert (toggle off)


# ---- per-symbol resilience (D2) — needs scheduler (Postgres deps) -----------

try:
    from app.tasks import scheduler as sched
except Exception:  # noqa: BLE001
    sched = None
requires_sched = pytest.mark.skipif(sched is None, reason="scheduler import needs db deps (run on server)")


def _seed_technical(db):
    from app.models.models import AssetConfig
    db.add(SourceConfig(source="technical", provider="kraken", enabled=True))
    for s in ("AAPL", "MSFT", "NVDA"):
        db.add(AssetConfig(symbol=s, asset_type="stock", enabled=True))
    db.commit()


@requires_sched
def test_one_flaky_symbol_stays_healthy(db, sent, monkeypatch):
    _enable_alerts(db)
    _seed_technical(db)
    from app.models.models import TechnicalSignal

    def fake_fetch(symbol, dbx):
        if symbol == "MSFT":
            raise RuntimeError("yfinance timeout")          # one flaky symbol
        dbx.add(TechnicalSignal(asset=symbol, indicator_name="rsi", signal_type="buy",
                                timestamp=datetime.datetime.utcnow()))
        dbx.commit()
    monkeypatch.setattr(sched, "fetch_and_analyze", fake_fetch)

    source_health.run_with_health(db, "technical", lambda: sched._run_technical(db))
    h = db.query(SourceHealth).filter(SourceHealth.source == "technical").first()
    assert h.last_state == "ok"        # 2 of 3 wrote → healthy, NOT error
    assert _errors(sent) == []          # one flaky symbol must not red-flag the source


@requires_sched
def test_systemic_failure_is_error(db, sent, monkeypatch):
    _enable_alerts(db)
    _seed_technical(db)
    monkeypatch.setattr(sched, "fetch_and_analyze",
                        lambda symbol, dbx: (_ for _ in ()).throw(RuntimeError("network down")))
    source_health.run_with_health(db, "technical", lambda: sched._run_technical(db))
    h = db.query(SourceHealth).filter(SourceHealth.source == "technical").first()
    assert h.last_state == "error"      # ALL symbols failed → systemic error
    assert len(_errors(sent)) == 1
