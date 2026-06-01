"""Backtest engine unit tests — the signal mirror + simulation math, on synthetic
data (no network, no pandas_ta; indicator columns are set by hand)."""
import datetime

import pandas as pd

from app.services import backtest as bt


def _row(rsi=50, sma20=100, sma50=100, dcl=90, dcu=110, close=100,
         macd=0.0, macds=0.0):
    return {"RSI_14": rsi, "SMA_20": sma20, "SMA_50": sma50,
            "DCL_20_20": dcl, "DCU_20_20": dcu, "Close": close,
            "MACD_12_26_9": macd, "MACDs_12_26_9": macds,
            "Open": close, "High": close, "Low": close}


def test_tech_reading_counts_neutrals_in_denominator():
    # 3 of 4 indicators bullish, 1 neutral -> strength 0.75 (NOT 1.0): neutrals
    # count in n, exactly like fusion._technical_reading.
    prev = _row(macd=-1.0, macds=0.0)
    cur = _row(rsi=25,                 # RSI < 30 -> buy
               sma20=110, sma50=100,   # MA cross -> buy
               dcl=100, dcu=110, close=110,  # Donchian pos=1.0 -> buy
               macd=0.0, macds=0.5)    # MACD: no crossover -> neutral
    df = pd.DataFrame([prev, cur])
    assert bt.tech_reading(df, 1) == ("bullish", 0.75)


def test_tech_reading_all_neutral_is_none():
    df = pd.DataFrame([_row(), _row()])  # RSI 50, MA flat(=neutral), Donchian mid, MACD flat
    assert bt.tech_reading(df, 1)[0] == "none"


def test_tech_reading_one_vote_below_arm_threshold():
    # Only MA votes buy, others neutral -> 1/4 = 0.25 (< 0.6 arm threshold).
    df = pd.DataFrame([_row(), _row(sma20=110, sma50=100)])
    assert bt.tech_reading(df, 1) == ("bullish", 0.25)


def test_tech_reading_four_of_four():
    prev = _row(macd=-1.0, macds=0.0)
    cur = _row(rsi=25, sma20=110, sma50=100, dcl=100, dcu=110, close=110, macd=1.0, macds=0.0)
    assert bt.tech_reading(df := pd.DataFrame([prev, cur]), 1) == ("bullish", 1.0)


def test_insider_score_cluster_beats_single():
    d = datetime.date(2026, 5, 20)
    as_of = datetime.datetime(2026, 5, 25)
    single = [{"filed": d, "insider": "A", "value": 1_000_000_000}]  # one huge buy
    cluster = [{"filed": d, "insider": x, "value": 200_000} for x in ("A", "B", "C")]
    # single insider caps ~0.6 (0.6*1/3 + 0.4*1.0); cluster of 3 hits higher.
    assert bt.insider_score(single, as_of) == 0.6
    assert bt.insider_score(cluster, as_of) > bt.insider_score(single, as_of)


def test_insider_score_windowed_out_of_lookback():
    old = [{"filed": datetime.date(2026, 1, 1), "insider": "A", "value": 600_000}]
    assert bt.insider_score(old, datetime.datetime(2026, 5, 1)) == 0.0  # > 14d before


def _price_df(rows):
    idx = pd.date_range("2026-01-01", periods=len(rows), freq="h")
    return pd.DataFrame(rows, index=idx)


def test_simulate_long_target_hit():
    # Enter long at bar0 close=100 (stock 6% stop -> stop 94, target 115); bar1 hits target.
    df = _price_df([
        {"Open": 100, "High": 100, "Low": 100, "Close": 100},
        {"Open": 100, "High": 116, "Low": 99, "Close": 115},
        {"Open": 115, "High": 115, "Low": 115, "Close": 115},
    ])
    trades = bt.simulate("AAPL", df, "stock", lambda i: "long" if i == 0 else None)
    assert len(trades) == 1
    t = trades[0]
    assert t["reason"] == "target" and t["pnl"] > 0
    # notional capped at 5% of 100k -> size 50; pnl = (115-100)*50 = 750
    assert t["size"] == 50.0 and t["pnl"] == 750.0


def test_simulate_short_stop_hit():
    # Short at 100, 6% stop -> stop 106; bar1 high 107 hits stop -> loss.
    df = _price_df([
        {"Open": 100, "High": 100, "Low": 100, "Close": 100},
        {"Open": 100, "High": 107, "Low": 99, "Close": 106},
    ])
    trades = bt.simulate("AAPL", df, "stock", lambda i: "short" if i == 0 else None)
    assert trades[0]["reason"] == "stop" and trades[0]["pnl"] < 0


def test_no_entry_when_signal_none():
    df = _price_df([{"Open": 100, "High": 101, "Low": 99, "Close": 100}] * 5)
    assert bt.simulate("AAPL", df, "stock", lambda i: None) == []


def test_metrics():
    trades = [
        {"pnl": 250.0, "exit_time": datetime.datetime(2026, 1, 2)},
        {"pnl": -100.0, "exit_time": datetime.datetime(2026, 1, 3)},
        {"pnl": 250.0, "exit_time": datetime.datetime(2026, 1, 4)},
    ]
    s = bt.summarize(trades)
    assert s["trades"] == 3 and s["wins"] == 2 and s["win_rate"] == round(2/3, 4)
    assert s["total_pnl"] == 400.0 and s["return_pct"] == 0.4
    # equity 100000 -> 100250 -> 100150 -> 100400; max DD = (100250-100150)/100250
    assert s["max_drawdown_pct"] == round(100/100250*100, 3)


def test_pullback_long_in_uptrend():
    # uptrend (close>trend), low dipped to pull MA, closed back above it -> long
    df = pd.DataFrame([{"Close": 110, "Low": 99, "High": 111, "SMA_PULL": 100, "SMA_TREND": 90}])
    assert bt.pullback_signal(df, 0) == "long"


def test_pullback_no_signal_when_broke_through():
    # uptrend but CLOSED below the pull MA (broke through, didn't bounce) -> no long
    df = pd.DataFrame([{"Close": 98, "Low": 97, "High": 101, "SMA_PULL": 100, "SMA_TREND": 90}])
    assert bt.pullback_signal(df, 0) is None


def test_pullback_no_signal_without_pullback_touch():
    # uptrend but low never reached the pull MA (no pullback) -> no entry
    df = pd.DataFrame([{"Close": 110, "Low": 105, "High": 112, "SMA_PULL": 100, "SMA_TREND": 90}])
    assert bt.pullback_signal(df, 0) is None


def test_pullback_short_in_downtrend():
    df = pd.DataFrame([{"Close": 90, "Low": 89, "High": 101, "SMA_PULL": 100, "SMA_TREND": 110}])
    assert bt.pullback_signal(df, 0) == "short"


def test_buy_and_hold():
    df = _price_df([{"Open": 100, "High": 100, "Low": 100, "Close": 100},
                    {"Open": 0, "High": 0, "Low": 0, "Close": 110}])
    assert bt.buy_and_hold_return(df) == 0.1
