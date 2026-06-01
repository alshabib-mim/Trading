"""Faithful backtest harness — replays the LIVE engine logic over historical 1h
candles, point-in-time, for the parts that can be honestly reconstructed:

  • STOCK engine: insider (Form 4, direction) + technical (timing gate) + 13F
    (support), point-in-time on EDGAR FILED dates (no lookahead).
  • FOREX/gold: technical-as-direction, macro nudge EXCLUDED.

Explicitly OUT (can't be faithfully reconstructed): whale/crypto direction,
macro (no history), sentiment (non-deterministic re-scoring). Every result is
benchmarked against buy-and-hold for the same asset over the same window.

The signal math mirrors the live modules EXACTLY (technical_analysis indicator
rules, fusion vote/arm/confidence, edgar insider scoring, risk sizing/stops) so
the replay reflects what the live system would have done — not a re-invention.
Constants are the live defaults; if those change, update here too.
"""
import datetime

import pandas as pd

# --- live config mirror (fusion DEFAULTS + risk DEFAULTS) --------------------
ARM_THRESHOLD = 0.6
W_DIR = 0.6
W_SUP = 0.1          # 13F support nudge
RR = 2.5             # take-profit reward:risk
RISK_PCT = 0.01      # risk_per_trade_pct 1%
MAX_POS_PCT = 0.05   # max_position_pct 5% (notional cap)
START_CAPITAL = 100000.0
INSIDER_LOOKBACK_DAYS = 14   # fusion insider freshness (1209600s)
INSIDER_BUYER_SCALE = 3
INSIDER_VALUE_SCALE = 500000
STOP_PCT = {"forex": 0.01, "stock": 0.06, "crypto": 0.06}
GOLD_STOP = 0.025    # XAU-USD by_symbol override


def _stop_pct(symbol, atype):
    if symbol == "XAU-USD":
        return GOLD_STOP
    return STOP_PCT.get(atype, 0.06)


# --- technical reading (mirrors technical_analysis.py + fusion._technical_reading) ---

def add_indicators(df):
    """Same indicators the live engine computes (pandas_ta_classic)."""
    import pandas_ta_classic  # noqa: F401 — registers the .ta accessor
    df = df.copy()
    df.ta.rsi(append=True)
    df.ta.macd(append=True)
    df.ta.sma(length=20, append=True)
    df.ta.sma(length=50, append=True)
    df.ta.donchian(lower_length=20, upper_length=20, append=True)
    return df


def tech_reading(df, i):
    """Point-in-time (direction, strength) at bar i — causal (rows <= i only),
    mirroring the live indicator buy/sell rules and the fusion vote count where
    strength = winning_votes / n_indicators (neutrals included in n)."""
    row = df.iloc[i]
    votes = []

    rsi = row.get("RSI_14")
    if pd.notna(rsi):
        votes.append("buy" if rsi < 30 else "sell" if rsi > 70 else "neutral")

    if i >= 1:
        p = df.iloc[i - 1]
        mp, sp, ml, sl = p.get("MACD_12_26_9"), p.get("MACDs_12_26_9"), row.get("MACD_12_26_9"), row.get("MACDs_12_26_9")
        if all(pd.notna(x) for x in (mp, sp, ml, sl)):
            if mp <= sp and ml > sl:
                votes.append("buy")
            elif mp >= sp and ml < sl:
                votes.append("sell")
            else:
                votes.append("neutral")

    fast, slow = row.get("SMA_20"), row.get("SMA_50")
    if pd.notna(fast) and pd.notna(slow):
        votes.append("buy" if fast > slow else "sell" if fast < slow else "neutral")

    dl, du, c = row.get("DCL_20_20"), row.get("DCU_20_20"), row.get("Close")
    if pd.notna(dl) and pd.notna(du) and du != dl:
        pos = (c - dl) / (du - dl)
        votes.append("buy" if pos >= 0.98 else "sell" if pos <= 0.02 else "neutral")

    if not votes:
        return ("none", 0.0)
    b, s, n = votes.count("buy"), votes.count("sell"), len(votes)
    if b > s:
        return ("bullish", round(b / n, 4))
    if s > b:
        return ("bearish", round(s / n, 4))
    return ("none", 0.0)


# --- insider scoring (mirrors edgar._score, windowed point-in-time) ----------

def insider_score(pbuys, as_of, lookback_days=INSIDER_LOOKBACK_DAYS):
    """edgar._score over P-buys FILED within (as_of - lookback, as_of]. pbuys is
    a list of {filed: date, insider: str, value: float}. Bullish-only."""
    cutoff = as_of - datetime.timedelta(days=lookback_days)
    active = [p for p in pbuys if cutoff < _as_dt(p["filed"]) <= as_of]
    if not active:
        return 0.0
    buyers = {p["insider"] for p in active}
    net = sum(p["value"] for p in active)
    score = 0.6 * min(len(buyers) / INSIDER_BUYER_SCALE, 1.0) + 0.4 * min(net / INSIDER_VALUE_SCALE, 1.0)
    return round(min(score, 1.0), 4)


def _as_dt(d):
    if isinstance(d, datetime.datetime):
        return d
    if isinstance(d, datetime.date):
        return datetime.datetime.combine(d, datetime.time.min)
    return datetime.datetime.fromisoformat(str(d))


# --- per-asset simulation (mirrors risk.py sizing/stops/exits) ---------------

def simulate(symbol, df, atype, signal_fn):
    """Step bar-by-bar. signal_fn(i) -> ('long'|'short'|None). Enters at the
    signal bar's close; manages stop/target intrabar (high/low) from the NEXT bar
    (no entry+exit on the same bar); one position at a time. Returns trade dicts."""
    stop_pct = _stop_pct(symbol, atype)
    trades = []
    pos = None
    idx = df.index
    for i in range(len(df)):
        bar = df.iloc[i]
        if pos is not None:
            hi, lo = bar["High"], bar["Low"]
            exit_price, reason = None, None
            if pos["side"] == "long":
                if lo <= pos["stop"]:
                    exit_price, reason = pos["stop"], "stop"
                elif hi >= pos["target"]:
                    exit_price, reason = pos["target"], "target"
            else:
                if hi >= pos["stop"]:
                    exit_price, reason = pos["stop"], "stop"
                elif lo <= pos["target"]:
                    exit_price, reason = pos["target"], "target"
            if exit_price is not None:
                trades.append(_close(symbol, pos, exit_price, idx[i], reason))
                pos = None

        if pos is None:
            side = signal_fn(i)
            if side:
                price = float(bar["Close"])
                sd = price * stop_pct
                if sd <= 0:
                    continue
                size = (RISK_PCT * START_CAPITAL) / sd
                if size * price > MAX_POS_PCT * START_CAPITAL:
                    size = (MAX_POS_PCT * START_CAPITAL) / price
                stop = price - sd if side == "long" else price + sd
                target = price + sd * RR if side == "long" else price - sd * RR
                pos = {"side": side, "entry": price, "stop": stop, "target": target,
                       "size": size, "entry_time": idx[i]}

    if pos is not None:  # mark-to-close any open position at the window end
        trades.append(_close(symbol, pos, float(df.iloc[-1]["Close"]), idx[-1], "eod"))
    return trades


def _close(symbol, pos, exit_price, exit_time, reason):
    pnl = (exit_price - pos["entry"]) * pos["size"] if pos["side"] == "long" \
        else (pos["entry"] - exit_price) * pos["size"]
    return {
        "symbol": symbol, "side": pos["side"], "entry": pos["entry"], "exit": exit_price,
        "size": pos["size"], "pnl": round(pnl, 2), "reason": reason,
        "entry_time": pos["entry_time"], "exit_time": exit_time,
    }


# --- metrics ----------------------------------------------------------------

def buy_and_hold_return(df):
    """Hold the asset long over the window: (last - first) / first."""
    first, last = float(df.iloc[0]["Close"]), float(df.iloc[-1]["Close"])
    return (last - first) / first if first else 0.0


def max_drawdown(equity_curve):
    """Max peak-to-trough drawdown of an equity curve (list of equity values)."""
    peak = equity_curve[0] if equity_curve else START_CAPITAL
    mdd = 0.0
    for e in equity_curve:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)
    return mdd


def summarize(trades, start_capital=START_CAPITAL):
    """win rate, total return %, max DD %, # trades — over a time-ordered ledger."""
    closed = sorted(trades, key=lambda t: t["exit_time"])
    wins = sum(1 for t in closed if t["pnl"] > 0)
    total_pnl = sum(t["pnl"] for t in closed)
    equity = [start_capital]
    for t in closed:
        equity.append(equity[-1] + t["pnl"])
    return {
        "trades": len(closed),
        "wins": wins,
        "losses": len(closed) - wins,
        "win_rate": round(wins / len(closed), 4) if closed else None,
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(total_pnl / start_capital * 100, 3),
        "max_drawdown_pct": round(max_drawdown(equity) * 100, 3),
    }
