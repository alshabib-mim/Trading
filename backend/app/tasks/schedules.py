"""Wall-clock (cron) schedules for the background jobs, on FIXED UTC boundaries.

Cron triggers fire at absolute wall-clock times, so a deploy/restart no longer
resets the cadence. (Interval triggers re-anchored to process start, which on a
busy deploy day starved the hourly+ jobs and gave the 15-min jobs transient lag.)

Sources are staggered to land BEFORE fusion so fusion reads fresh writes that tick.

Pure data — no app/db imports — so the schedule can be unit-tested standalone.
"""

# job id -> APScheduler cron kwargs (interpreted in UTC; the scheduler is tz=UTC).
CRON = {
    "technical":     {"minute": "0,15,30,45"},        # every 15 min, on the quarter
    "whale":         {"minute": "1,16,31,46"},        # 15 min, just after technical
    "macro":         {"minute": "0,15,30,45"},        # 15-min gate tick; run_macro gates on run_times
    "fusion":        {"minute": "7,22,37,52"},        # 15 min, AFTER the sources write
    "risk":          {"minute": "*/5"},               # every 5 min
    "sentiment":     {"minute": "7"},                 # hourly, at :07
    "insider":       {"hour": "0,6,12,18", "minute": "10"},   # every 6h at :10
    "institutional": {"hour": "1", "minute": "20"},   # daily 01:20 UTC (13F)
    "cleanup":       {"hour": "3", "minute": "30"},   # daily 03:30 UTC
}

# Option 2, limited to TECHNICAL ONLY: re-run once on startup so a deploy refreshes
# prices immediately. Technical is FREE. Never sentiment/macro/insider/institutional
# here — those cost money (Claude) or hit rate-limited free tiers, and a deploy must
# not trigger paid/throttled calls.
RUN_ON_STARTUP = ("technical",)
