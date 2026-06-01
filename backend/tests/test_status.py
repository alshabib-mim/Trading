"""Market-status + next-run calculations, verified against the actual schedules."""
import datetime

import pytest
from types import SimpleNamespace

from app.services import macro, market_hours

# Anchored weekdays (2026-06-01 is a Monday): a normal week + its weekend.
WED = datetime.datetime(2026, 6, 3, 0, 0)
FRI = datetime.datetime(2026, 6, 5, 0, 0)
SAT = datetime.datetime(2026, 6, 6, 0, 0)
SUN = datetime.datetime(2026, 6, 7, 0, 0)
MON = datetime.datetime(2026, 6, 8, 0, 0)


def _cfg(run_times, skip=True):
    return SimpleNamespace(options={"run_times": run_times, "skip_forex_weekend": skip}, enabled=True)


# ---- macro.next_fetch_at (daily / twice-daily, weekend-aware) ---------------

def test_next_fetch_once_daily_same_day_and_next_day():
    cfg = _cfg(["13:00"])
    assert macro.next_fetch_at(cfg, WED.replace(hour=10)) == WED.replace(hour=13)   # later today
    assert macro.next_fetch_at(cfg, WED.replace(hour=14)) == WED.replace(hour=13) + datetime.timedelta(days=1)


def test_next_fetch_skips_the_weekend():
    cfg = _cfg(["13:00"])
    # Friday after the 13:00 slot → next is MONDAY 13:00 (Sat/Sun slots skipped).
    assert macro.next_fetch_at(cfg, FRI.replace(hour=14)) == MON.replace(hour=13)
    # Saturday morning → Monday 13:00.
    assert macro.next_fetch_at(cfg, SAT.replace(hour=9)) == MON.replace(hour=13)
    # Sunday 23:00 (market reopened at 22:00) → Monday 13:00.
    assert macro.next_fetch_at(cfg, SUN.replace(hour=23)) == MON.replace(hour=13)


def test_next_fetch_twice_daily():
    cfg = _cfg(["08:00", "20:00"])
    assert macro.next_fetch_at(cfg, WED.replace(hour=9)) == WED.replace(hour=20)
    assert macro.next_fetch_at(cfg, WED.replace(hour=21)) == WED.replace(hour=8) + datetime.timedelta(days=1)


def test_next_fetch_without_weekend_skip_runs_saturday():
    cfg = _cfg(["13:00"], skip=False)
    assert macro.next_fetch_at(cfg, FRI.replace(hour=14)) == SAT.replace(hour=13)


# ---- market status ---------------------------------------------------------

def test_crypto_always_open():
    assert market_hours.crypto_status(SAT)["open"] is True
    assert market_hours.crypto_status(WED)["open"] is True


def test_forex_reuses_weekend_logic():
    assert market_hours.forex_status(FRI.replace(hour=21, minute=59))["open"] is True
    assert market_hours.forex_status(FRI.replace(hour=22))["open"] is False
    assert market_hours.forex_status(SAT.replace(hour=12))["open"] is False
    assert market_hours.forex_status(SUN.replace(hour=22))["open"] is True
    assert market_hours.forex_status(WED.replace(hour=3))["open"] is True


@pytest.mark.skipif(market_hours._NY is None, reason="tz database unavailable")
def test_stock_us_hours():
    # June 2026 → EDT (UTC-4): 13:30–20:00 UTC == 09:30–16:00 ET.
    assert market_hours.stock_status(WED.replace(hour=14))["open"] is True       # 10:00 ET
    assert market_hours.stock_status(WED.replace(hour=13, minute=29))["open"] is False  # 09:29 ET
    assert market_hours.stock_status(WED.replace(hour=20))["open"] is False      # 16:00 ET (closed edge)
    assert market_hours.stock_status(WED.replace(hour=2))["open"] is False       # overnight
    assert market_hours.stock_status(SAT.replace(hour=15))["open"] is False      # weekend
    assert "regular-hours only" in market_hours.stock_status(WED)["detail"]
