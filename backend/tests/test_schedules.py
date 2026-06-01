"""Cron schedule tests — verify jobs fire on fixed UTC boundaries, and that the
next fire is the SAME boundary regardless of when the process (re)started. This
is the property that fixes the deploy-induced timer-reset staleness.

Uses CronTrigger directly against the pure schedules.CRON data (no app/db import).
"""
import datetime

import pytz
from apscheduler.triggers.cron import CronTrigger

from app.tasks.schedules import CRON, RUN_ON_STARTUP


def _utc(y, mo, d, h, mi, s=0):
    return datetime.datetime(y, mo, d, h, mi, s, tzinfo=pytz.utc)


def _next(job, now):
    # previous_fire_time=None → next fire at/after `now`. Cron ignores `now`'s
    # offset from any "start", which is exactly the restart-independence we want.
    return CronTrigger(timezone=pytz.utc, **CRON[job]).get_next_fire_time(None, now)


def test_technical_on_quarter_hours():
    assert _next("technical", _utc(2026, 6, 3, 12, 7, 33)) == _utc(2026, 6, 3, 12, 15)
    assert _next("technical", _utc(2026, 6, 3, 12, 14, 59)) == _utc(2026, 6, 3, 12, 15)
    assert _next("technical", _utc(2026, 6, 3, 12, 46, 0)) == _utc(2026, 6, 3, 13, 0)


def test_next_fire_is_restart_independent():
    # THE fix: two different "restart" instants WITHIN THE SAME inter-fire gap both
    # resolve to the same next boundary — restart timing no longer shifts cadence.
    # (next fire depends only on `now`, never on any process-start reference.)
    cases = [
        ("technical", _utc(2026, 6, 3, 12, 1), _utc(2026, 6, 3, 12, 14), _utc(2026, 6, 3, 12, 15)),
        ("whale", _utc(2026, 6, 3, 12, 2), _utc(2026, 6, 3, 12, 15), _utc(2026, 6, 3, 12, 16)),
        ("fusion", _utc(2026, 6, 3, 12, 8), _utc(2026, 6, 3, 12, 20), _utc(2026, 6, 3, 12, 22)),
    ]
    for job, restart_a, restart_b, boundary in cases:
        assert _next(job, restart_a) == _next(job, restart_b) == boundary


def test_sentiment_hourly_at_07_starved_no_more():
    # Hourly at :07 — the job that the restart cascade starved. Now a restart at
    # 12:50 or 12:55 still fires at 13:07, never deferred past the hour.
    assert _next("sentiment", _utc(2026, 6, 3, 12, 3)) == _utc(2026, 6, 3, 12, 7)
    assert _next("sentiment", _utc(2026, 6, 3, 12, 30)) == _utc(2026, 6, 3, 13, 7)
    assert _next("sentiment", _utc(2026, 6, 3, 12, 50)) == _next("sentiment", _utc(2026, 6, 3, 12, 55)) == _utc(2026, 6, 3, 13, 7)


def test_insider_six_hourly():
    assert _next("insider", _utc(2026, 6, 3, 3, 0)) == _utc(2026, 6, 3, 6, 10)
    assert _next("insider", _utc(2026, 6, 3, 6, 11)) == _utc(2026, 6, 3, 12, 10)


def test_institutional_and_cleanup_daily():
    assert _next("institutional", _utc(2026, 6, 3, 2, 0)) == _utc(2026, 6, 4, 1, 20)
    assert _next("cleanup", _utc(2026, 6, 3, 4, 0)) == _utc(2026, 6, 4, 3, 30)


def test_macro_tick_quarter_hours():
    assert _next("macro", _utc(2026, 6, 3, 12, 1)) == _utc(2026, 6, 3, 12, 15)


def test_risk_every_5_min():
    assert _next("risk", _utc(2026, 6, 3, 12, 7, 10)) == _utc(2026, 6, 3, 12, 10)


def test_run_on_startup_is_technical_only():
    # The cost guardrail: only the FREE source runs on deploy.
    assert tuple(RUN_ON_STARTUP) == ("technical",)
    for paid in ("sentiment", "macro", "insider", "institutional", "whale"):
        assert paid not in RUN_ON_STARTUP


def test_every_job_has_a_schedule():
    # No job silently missing a cron entry.
    for job in ("technical", "whale", "macro", "fusion", "risk", "sentiment",
                "insider", "institutional", "cleanup"):
        assert job in CRON
