"""Alerts layer tests — Telegram send path, master/event toggles, the four event
message formats, and the watch→pending "signal armed" alert end-to-end through
fuse_asset. The risk-engine wiring tests (position/exit/breaker) import the risk
engine, which pulls market_data's heavy deps (ccxt/yfinance) — they skip locally
and run on the server (full venv) during verification.
"""
import os
import base64
import datetime

# A valid 32-byte (AES-256) key for encrypt()/decrypt() in tests — set before import.
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"0123456789abcdef0123456789abcdef").decode())

import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, AlertConfig, AssetConfig, SourceConfig, TechnicalSignal, TradingSignal, RiskState,
)
from app.core.crypto import encrypt
from app.services import alerts, fusion

# Risk engine imports market_data (ccxt/yfinance) — optional locally.
try:
    from app.services import risk as risk_engine
except Exception:  # noqa: BLE001
    risk_engine = None
requires_risk = pytest.mark.skipif(
    risk_engine is None, reason="risk engine deps (ccxt/yfinance) not installed in this venv"
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


@pytest.fixture
def sent(monkeypatch):
    """Capture Telegram sends without hitting the network."""
    calls = []

    class _Resp:
        status_code = 200
        def json(self):  # noqa: D401
            return {"ok": True}

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json})
        return _Resp()

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    return calls


def _enable_alerts(db, events=None, enabled=True):
    row = AlertConfig(
        channel="telegram", enabled=enabled,
        bot_token_encrypted=encrypt("123:ABC"),
        chat_id_encrypted=encrypt("999"),
        events=events if events is not None else dict(alerts.DEFAULT_EVENTS),
    )
    db.add(row)
    db.commit()
    return row


# ---- send path + toggles ---------------------------------------------------

def test_send_message_builds_telegram_request(db, sent):
    _enable_alerts(db)
    ok, detail = alerts.send_message("hello", db)
    assert ok and detail == "sent"
    assert len(sent) == 1
    assert sent[0]["url"].endswith("/bot123:ABC/sendMessage")
    assert sent[0]["json"]["chat_id"] == "999"
    assert sent[0]["json"]["text"] == "hello"


def test_send_message_requires_creds(db, sent):
    db.add(AlertConfig(channel="telegram", enabled=True, events=dict(alerts.DEFAULT_EVENTS)))
    db.commit()
    ok, detail = alerts.send_message("x", db)
    assert ok is False and "required" in detail
    assert sent == []


def test_emit_blocked_when_master_disabled(db, sent):
    _enable_alerts(db, enabled=False)
    assert alerts._emit("signal_armed", "x", db) is False
    assert sent == []


def test_emit_blocked_when_event_off(db, sent):
    _enable_alerts(db, events={**alerts.DEFAULT_EVENTS, "signal_armed": False})
    assert alerts._emit("signal_armed", "x", db) is False
    assert sent == []
    # a different event type still goes through
    assert alerts._emit("breaker", "y", db) is True
    assert len(sent) == 1


def test_no_config_row_never_sends(db, sent):
    assert alerts._emit("signal_armed", "x", db) is False
    assert sent == []


# ---- the four message formats ----------------------------------------------

def test_signal_armed_message(db, sent):
    _enable_alerts(db)
    sig = SimpleNamespace(asset="EUR-USD", direction="bearish", signal_type="sell",
                          confidence_score=0.72, technical_conf=True, news_conf=True,
                          sentiment_conf=False, institutional_conf=None, whale_conf=None)
    assert alerts.signal_armed(sig, db) is True
    text = sent[0]["json"]["text"]
    assert "SIGNAL ARMED" in text and "EUR-USD" in text and "BEARISH" in text
    assert "72%" in text and "technical" in text and "macro news" in text


def test_position_opened_message(db, sent):
    _enable_alerts(db)
    trade = SimpleNamespace(asset="EUR-USD", side="short", entry_price=1.16497,
                            size=0.12, stop_loss=1.17, take_profit=1.15)
    assert alerts.position_opened(trade, db) is True
    text = sent[0]["json"]["text"]
    assert "POSITION OPENED" in text and "EUR-USD" in text and "SHORT" in text and "1.16497" in text


def test_exit_hit_target_and_stop(db, sent):
    _enable_alerts(db)
    win = SimpleNamespace(asset="EUR-USD", side="short", close_reason="target",
                          exit_price=1.15, pnl=123.45)
    alerts.exit_hit(win, db)
    assert "TARGET HIT" in sent[-1]["json"]["text"] and "+$123.45" in sent[-1]["json"]["text"]
    loss = SimpleNamespace(asset="EUR-USD", side="short", close_reason="stop",
                           exit_price=1.17, pnl=-80.0)
    alerts.exit_hit(loss, db)
    assert "STOP HIT" in sent[-1]["json"]["text"] and "-$80.00" in sent[-1]["json"]["text"]


def test_breaker_message(db, sent):
    _enable_alerts(db)
    assert alerts.breaker_fired(["daily_loss (-2100 ≤ -2000)"], 98000.0, db) is True
    text = sent[0]["json"]["text"]
    assert "CIRCUIT BREAKER" in text and "daily_loss" in text and "$98,000.00" in text


# ---- synthetic armed-signal end-to-end (the headline verification) ---------

def _seed_armed_forex(db):
    db.add(AssetConfig(symbol="EUR-USD", asset_type="forex", enabled=True))
    db.add(SourceConfig(source="technical", provider="td", enabled=True, freshness_seconds=3600))
    db.commit()


def _strong_bearish_tech(db, now):
    for name in ("rsi", "macd", "ema"):  # 3 sells, 0 buys → bearish strength 1.0
        db.add(TechnicalSignal(asset="EUR-USD", indicator_name=name, signal_type="sell", timestamp=now))
    db.commit()


def test_fusion_arming_fires_signal_alert_once(db, sent, monkeypatch):
    # Armed rows call Claude for reasoning — stub it so the test never hits the API.
    monkeypatch.setattr("app.services.reasoning.generate_reasoning", lambda ctx, db: "stub")
    _enable_alerts(db)
    _seed_armed_forex(db)
    now = datetime.datetime.utcnow()
    _strong_bearish_tech(db, now)

    # First cycle: watch → pending → ONE "signal armed" alert.
    row = fusion.fuse_asset("EUR-USD", db, now=now)
    assert row.status == "pending"
    assert len(sent) == 1
    assert "SIGNAL ARMED" in sent[0]["json"]["text"] and "EUR-USD" in sent[0]["json"]["text"]

    # Second cycle, still armed: NO repeat alert (edge-triggered, not level).
    fusion.fuse_asset("EUR-USD", db, now=now + datetime.timedelta(minutes=15))
    assert len(sent) == 1

    # Direction collapses to watch (technicals gone), then re-arms → a NEW alert.
    db.query(TechnicalSignal).delete()
    db.commit()
    fusion.fuse_asset("EUR-USD", db, now=now + datetime.timedelta(minutes=30))
    assert len(sent) == 1  # watch row, no alert
    _strong_bearish_tech(db, now + datetime.timedelta(minutes=45))
    fusion.fuse_asset("EUR-USD", db, now=now + datetime.timedelta(minutes=45))
    assert len(sent) == 2  # re-armed → fires again


def test_fusion_arming_silent_when_alerts_disabled(db, sent, monkeypatch):
    monkeypatch.setattr("app.services.reasoning.generate_reasoning", lambda ctx, db: "stub")
    _enable_alerts(db, enabled=False)
    _seed_armed_forex(db)
    now = datetime.datetime.utcnow()
    _strong_bearish_tech(db, now)
    row = fusion.fuse_asset("EUR-USD", db, now=now)
    assert row.status == "pending"
    assert sent == []  # armed, but alerts off → silent


# ---- risk-engine wiring (server venv) --------------------------------------

@requires_risk
def test_breaker_edge_fires_once_then_clears(db, sent):
    # Seed a halted state (manual kill switch) and no trades.
    cap = 100000.0
    db.add(RiskState(peak_equity=cap, day_start_equity=cap, manual_halt=True, day_date=None))
    db.commit()
    price_fn = lambda a: None  # no positions → no market data needed  # noqa: E731

    risk_engine.run_risk_engine(db, price_fn=price_fn)
    breaker_msgs = [c for c in sent if "CIRCUIT BREAKER" in c["json"]["text"]]
    assert len(breaker_msgs) == 1  # fired once on engage
    assert "manual_halt" in breaker_msgs[0]["json"]["text"]

    # Still halted next tick → no repeat.
    risk_engine.run_risk_engine(db, price_fn=price_fn)
    assert len([c for c in sent if "CIRCUIT BREAKER" in c["json"]["text"]]) == 1

    # Clear the halt → no alert, and the edge memory resets.
    state = db.query(RiskState).first()
    state.manual_halt = False
    db.commit()
    risk_engine.run_risk_engine(db, price_fn=price_fn)
    assert len([c for c in sent if "CIRCUIT BREAKER" in c["json"]["text"]]) == 1
    assert db.query(RiskState).first().halt_alerted is None


@requires_risk
def test_position_open_and_exit_alerts(db, sent):
    # One pending signal + a controlled price → engine opens a paper position.
    cap = 100000.0
    db.add(RiskState(peak_equity=cap, day_start_equity=cap, manual_halt=False, day_date=None))
    db.add(AssetConfig(symbol="EUR-USD", asset_type="forex", enabled=True))
    db.add(TradingSignal(asset="EUR-USD", direction="bullish", signal_type="buy",
                         confidence_score=0.9, status="pending", timestamp=datetime.datetime.utcnow()))
    db.commit()

    risk_engine.run_risk_engine(db, price_fn=lambda a: 1.20)
    assert any("POSITION OPENED" in c["json"]["text"] for c in sent)

    # Drop the price below the stop → engine closes on stop → exit alert.
    risk_engine.run_risk_engine(db, price_fn=lambda a: 0.50)
    assert any("STOP HIT" in c["json"]["text"] for c in sent)
