"""Forex macro-news (4th signal source) — the load-bearing safety tests.

The contract the user gated on: a SINGLE macro event must produce OPPOSITE,
correct directions across pairs (hawkish Fed → bullish USD → bearish EUR/USD AND
bullish USD/JPY), gold must be read DIRECTLY (not decomposed), unverified data
must fail safe to NO reading (never a fabricated direction), and news must NUDGE
confidence without ever FLIPPING the technical-owned direction.
"""
import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, MacroBias, AssetConfig, SourceConfig, TechnicalSignal,
)
from app.services import macro, fusion


@pytest.fixture(autouse=True)
def _no_real_reasoning(monkeypatch):
    # Armed rows call Claude for reasoning; stub it so tests never hit the API.
    monkeypatch.setattr(
        "app.services.reasoning.generate_reasoning",
        lambda ctx, db: "stub-reasoning",
    )


# ---- pure derivation core (no DB) ------------------------------------------

def _snapshot(currencies, gold=None):
    return MacroBias(currencies=currencies, gold=gold,
                     timestamp=datetime.datetime.utcnow())


# A single macro event: hawkish Fed → USD strongly bullish; everything else flat.
HAWKISH_FED = _snapshot(
    currencies={
        "USD": {"bias": "bullish", "strength": 0.8, "why": "Fed hawkish hold"},
        "EUR": {"bias": "neutral", "strength": 0.1, "why": "no major release"},
        "JPY": {"bias": "neutral", "strength": 0.1, "why": "BoJ on hold"},
    },
    gold={"direction": "bearish", "strength": 0.6, "why": "strong USD + higher real yields"},
)


def test_single_event_opposite_directions_across_pairs():
    """THE must-pass test: one event, opposite correct directions per pair."""
    eurusd = macro.pair_reading("EUR-USD", HAWKISH_FED)
    usdjpy = macro.pair_reading("USD-JPY", HAWKISH_FED)

    # Bullish USD ⇒ bearish EUR/USD (USD is the quote) ...
    assert eurusd["direction"] == "bearish"
    # ... AND bullish USD/JPY (USD is the base) — same event, opposite directions.
    assert usdjpy["direction"] == "bullish"

    # Conviction = |net bias|; here |0 − 0.8| = 0.8 on both legs.
    assert eurusd["conviction"] == pytest.approx(0.8)
    assert usdjpy["conviction"] == pytest.approx(0.8)


def test_gold_is_direct_read_not_decomposed():
    """XAU-USD uses gold's own driver read (0.6), NOT a USD decomposition (which
    would have leaked 0.8 from the USD bias)."""
    xau = macro.pair_reading("XAU-USD", HAWKISH_FED)
    assert xau["direction"] == "bearish"
    assert xau["conviction"] == pytest.approx(0.6)  # gold's strength, not USD's 0.8


def test_insufficient_currency_fails_safe_to_no_reading():
    """A currency Claude couldn't verify ⇒ the whole pair gets NO reading
    (never a fabricated direction)."""
    snap = _snapshot({
        "USD": {"bias": "bullish", "strength": 0.8, "why": "Fed"},
        "GBP": {"bias": "insufficient", "strength": 0.0, "why": "no verified data"},
    })
    assert macro.pair_reading("GBP-USD", snap) is None


def test_gold_insufficient_and_neutral():
    assert macro.pair_reading("XAU-USD", _snapshot({}, gold={"direction": "insufficient", "strength": 0.0})) is None
    neutral = macro.pair_reading("XAU-USD", _snapshot({}, gold={"direction": "neutral", "strength": 0.0}))
    assert neutral == {"direction": "none", "conviction": 0.0}


def test_both_legs_neutral_is_none():
    snap = _snapshot({
        "EUR": {"bias": "neutral", "strength": 0.2, "why": "x"},
        "USD": {"bias": "neutral", "strength": 0.2, "why": "y"},
    })
    assert macro.pair_reading("EUR-USD", snap) == {"direction": "none", "conviction": 0.0}


def test_no_snapshot_is_none():
    assert macro.pair_reading("EUR-USD", None) is None


def test_extract_json_prefers_fence_and_refuses_garbage():
    good = 'blah blah\n```json\n{"currencies": {"USD": {"bias":"bullish","strength":0.5,"why":"x"}}}\n```'
    assert macro._extract_json(good)["currencies"]["USD"]["bias"] == "bullish"
    assert macro._extract_json("no json here at all") is None
    assert macro._extract_json("") is None


# ---- fusion integration: nudge, never flip (DB) ----------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _seed_forex(db, tech_votes):
    """Forex asset EUR-USD with technical + macro enabled; seed technical votes."""
    now = datetime.datetime.utcnow()
    db.add(AssetConfig(symbol="EUR-USD", asset_type="forex", enabled=True))
    db.add(SourceConfig(source="technical", provider="td", enabled=True, freshness_seconds=3600))
    db.add(SourceConfig(source="macro", provider="claude_websearch", enabled=True, freshness_seconds=43200))
    for name, vote in tech_votes:
        db.add(TechnicalSignal(asset="EUR-USD", indicator_name=name, signal_type=vote, timestamp=now))
    db.commit()


# 3 sells / 2 buys ⇒ technical bearish, strength 0.6 (base confidence before news).
BEARISH_TECH = [("rsi", "sell"), ("macd", "sell"), ("ema", "sell"), ("sma", "buy"), ("bb", "buy")]


def test_news_confirms_raises_confidence(db):
    _seed_forex(db, BEARISH_TECH)
    # USD bullish ⇒ EUR/USD news = bearish, which CONFIRMS the bearish technical.
    db.add(MacroBias(
        currencies={"USD": {"bias": "bullish", "strength": 0.8, "why": "Fed"},
                    "EUR": {"bias": "neutral", "strength": 0.1, "why": "x"}},
        timestamp=datetime.datetime.utcnow()))
    db.commit()

    row = fusion.fuse_asset("EUR-USD", db)
    assert row.direction == "bearish"
    assert row.news_conf is True
    # 0.6 + w_news(0.15) * 0.8 = 0.72
    assert row.confidence_score == pytest.approx(0.72)


def test_news_contradicts_dampens_but_never_flips(db):
    _seed_forex(db, BEARISH_TECH)
    # USD bearish ⇒ EUR/USD news = bullish, which CONTRADICTS the bearish technical.
    db.add(MacroBias(
        currencies={"USD": {"bias": "bearish", "strength": 0.8, "why": "dovish Fed"},
                    "EUR": {"bias": "neutral", "strength": 0.1, "why": "x"}},
        timestamp=datetime.datetime.utcnow()))
    db.commit()

    row = fusion.fuse_asset("EUR-USD", db)
    # Direction is STILL bearish — technical owns it; news cannot flip it.
    assert row.direction == "bearish"
    assert row.news_conf is False
    # 0.6 − 0.15 * 0.8 = 0.48 (dampened, not flipped).
    assert row.confidence_score == pytest.approx(0.48)


def test_no_macro_snapshot_leaves_technical_untouched(db):
    _seed_forex(db, BEARISH_TECH)  # macro enabled but NO snapshot rows
    row = fusion.fuse_asset("EUR-USD", db)
    assert row.direction == "bearish"
    assert row.news_conf is False          # nothing confirmed
    assert row.confidence_score == pytest.approx(0.6)  # pure technical strength


# ---- schedule gating: forex weekend + cadence ------------------------------

from types import SimpleNamespace

# Anchored weekdays (verified in test_anchor_dates): a normal trading week and
# its weekend. 2026-06-01 is a Monday.
WED = datetime.datetime(2026, 6, 3, 13, 0)    # Wednesday 13:00 UTC
FRI = datetime.datetime(2026, 6, 5, 0, 0)     # Friday
SAT = datetime.datetime(2026, 6, 6, 0, 0)     # Saturday
SUN = datetime.datetime(2026, 6, 7, 0, 0)     # Sunday
MON = datetime.datetime(2026, 6, 8, 0, 0)     # Monday (next week)


def _cfg(enabled=True, **opts):
    base = {"run_times": ["13:00"], "skip_forex_weekend": True}
    base.update(opts)
    return SimpleNamespace(enabled=enabled, options=base)


def test_anchor_dates():
    assert (WED.weekday(), FRI.weekday(), SAT.weekday(), SUN.weekday(), MON.weekday()) == (2, 4, 5, 6, 0)


def test_forex_market_open_weekend_boundaries():
    assert macro.forex_market_open(FRI.replace(hour=21, minute=59)) is True   # Fri before close
    assert macro.forex_market_open(FRI.replace(hour=22)) is False             # Fri 22:00 close
    assert macro.forex_market_open(SAT.replace(hour=12)) is False             # Saturday
    assert macro.forex_market_open(SUN.replace(hour=21, minute=59)) is False  # Sun before reopen
    assert macro.forex_market_open(SUN.replace(hour=22)) is True              # Sun 22:00 reopen
    assert macro.forex_market_open(MON.replace(hour=9)) is True               # weekday
    assert macro.forex_market_open(WED) is True


def test_cadence_once_daily_fires_once_per_slot():
    cfg = _cfg(run_times=["13:00"])
    # Yesterday's snapshot, now it's today's 13:00 slot → due.
    assert macro.due_to_run(cfg, WED.replace(hour=13), WED.replace(hour=13) - datetime.timedelta(days=1)) is True
    # Before today's slot → not due.
    assert macro.due_to_run(cfg, WED.replace(hour=12, minute=59), WED - datetime.timedelta(days=1)) is False
    # Already ran at the slot → deduped (no second fire on the next tick).
    assert macro.due_to_run(cfg, WED.replace(hour=13, minute=15), WED.replace(hour=13)) is False


def test_cadence_twice_daily_two_slots():
    cfg = _cfg(run_times=["08:00", "20:00"])
    eight = WED.replace(hour=8)
    twenty = WED.replace(hour=20)
    # 08:00 slot fires given last run was the prior evening.
    assert macro.due_to_run(cfg, eight, WED.replace(hour=20) - datetime.timedelta(days=1)) is True
    # After running at 08:00, the 20:00 slot is the next fire.
    assert macro.due_to_run(cfg, twenty, eight) is True
    # Between the two slots → no extra fire.
    assert macro.due_to_run(cfg, WED.replace(hour=14), eight) is False


def test_weekend_is_skipped_and_not_caught_up_at_reopen():
    cfg = _cfg(run_times=["13:00"])
    fri_run = FRI.replace(hour=13)  # last good run: Friday 13:00
    # Saturday 13:00 slot → market closed → skipped.
    assert macro.due_to_run(cfg, SAT.replace(hour=13), fri_run) is False
    # Sunday 13:00 slot → still closed → skipped.
    assert macro.due_to_run(cfg, SUN.replace(hour=13), fri_run) is False
    # Just after Sunday 22:00 reopen → the skipped weekend slots are NOT caught up.
    assert macro.due_to_run(cfg, SUN.replace(hour=22, minute=30), fri_run) is False
    # Monday's 13:00 slot → resumes normally.
    assert macro.due_to_run(cfg, MON.replace(hour=13), fri_run) is True


def test_skip_weekend_disabled_allows_weekend_runs():
    cfg = _cfg(run_times=["13:00"], skip_forex_weekend=False)
    # With the weekend guard off, a Saturday slot fires.
    assert macro.due_to_run(cfg, SAT.replace(hour=13), FRI.replace(hour=13)) is True


def test_disabled_source_never_due():
    assert macro.due_to_run(_cfg(enabled=False), WED.replace(hour=13), None) is False


def test_weekday_missed_slot_is_caught_up():
    cfg = _cfg(run_times=["13:00"])
    # Wednesday run failed (last good = Tuesday 13:00); a later Wednesday tick catches up.
    tue_run = WED.replace(hour=13) - datetime.timedelta(days=1)
    assert macro.due_to_run(cfg, WED.replace(hour=15), tue_run) is True


def test_run_macro_gates_against_db(db, monkeypatch):
    """End-to-end wiring: run_macro reads the macro config row + last snapshot and
    only calls the (paid) fetch when due. fetch is stubbed — no API call."""
    calls = {"n": 0}
    sim = {"now": WED}

    def _stub_fetch(db_, cfg_):
        # Stamp the snapshot at the SIMULATED now so dedupe compares like-for-like.
        calls["n"] += 1
        row = MacroBias(currencies={"USD": {"bias": "bullish", "strength": 0.5, "why": "x"}},
                        timestamp=sim["now"])
        db_.add(row); db_.commit()
        return row
    monkeypatch.setattr(macro, "fetch_macro_bias", _stub_fetch)

    def _run(now):
        sim["now"] = now
        return macro.run_macro(db, now=now)

    # Disabled → never fetches, even on a valid slot.
    db.add(SourceConfig(source="macro", provider="claude_websearch", enabled=False,
                        freshness_seconds=288000,
                        options={"run_times": ["13:00"], "skip_forex_weekend": True}))
    db.commit()
    assert _run(WED.replace(hour=13)) is None
    assert calls["n"] == 0

    # Enable it → due at the 13:00 slot → fetches once.
    db.query(SourceConfig).filter(SourceConfig.source == "macro").first().enabled = True
    db.commit()
    assert _run(WED.replace(hour=13)) is not None
    assert calls["n"] == 1

    # Next tick, same slot → deduped (snapshot now newer than the slot).
    assert _run(WED.replace(hour=13, minute=15)) is None
    assert calls["n"] == 1

    # On the Saturday → weekend-skipped even though a day has passed.
    assert _run(SAT.replace(hour=13)) is None
    assert calls["n"] == 1

    # force=True bypasses the schedule gate (manual refresh path).
    sim["now"] = SAT.replace(hour=13)
    assert macro.run_macro(db, now=SAT.replace(hour=13), force=True) is not None
    assert calls["n"] == 2
