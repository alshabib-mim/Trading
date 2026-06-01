"""Risk-control + simulated (paper) execution engine.

Paper mode only — no broker, no real money. Each tick (~5 min):
  1. mark open positions to the latest 1h candle close; compute equity
  2. update risk_state (peak equity, daily baseline)
  3. evaluate circuit breakers (daily-loss, drawdown, manual halt) — GLOBAL only
  4. close any open position whose stop/target is hit
  5. open paper positions for newly-armed (pending) signals that pass the gates

Config is read from risk_config at runtime (owner-editable, no redeploy).
Per-trade overrides apply ONLY to stop_loss / take_profit (resolve()); the
account-level breakers are global-only by design.
"""
import datetime

from sqlalchemy.orm import Session

from app.models.models import (
    RiskConfig, RiskState, ExecutedTrade, TradingSignal, SourceConfig,
)
from app.services.market_data import get_ohlcv
from app.services import assets, twelvedata

DEFAULTS = {
    "account": {"starting_capital": 100000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 5.0},
    "daily_loss": {"limit_pct": 2.0},
    "drawdown": {"limit_pct": 10.0},
    "max_concurrent": {"max": 5},
    "stop_loss": {"pct": 6.0},
    "take_profit": {"rr": 2.5},
}


def _config_map(db):
    out = {}
    for row in db.query(RiskConfig).all():
        out[row.key] = {"enabled": bool(row.enabled), "params": row.params or {}}
    return out


def _get_state(db):
    state = db.query(RiskState).first()
    if state is None:
        cap = _account(_config_map(db))[0]
        state = RiskState(peak_equity=cap, day_start_equity=cap, manual_halt=False)
        db.add(state)
        db.commit()
    return state


def resolve(cfg_map, key, trade=None):
    """Effective (enabled, params). Per-trade override only for stop_loss/take_profit."""
    base = cfg_map.get(key) or {"enabled": True, "params": DEFAULTS.get(key, {})}
    enabled = base["enabled"]
    params = {**DEFAULTS.get(key, {}), **(base.get("params") or {})}
    if trade is not None and key in ("stop_loss", "take_profit") and trade.overrides:
        ov = trade.overrides.get(key)
        if ov:
            if "enabled" in ov:
                enabled = bool(ov["enabled"])
            params = {**params, **(ov.get("params") or {})}
    return enabled, params


def _account(cfg_map):
    p = {**DEFAULTS["account"], **((cfg_map.get("account") or {}).get("params") or {})}
    return p["starting_capital"], p["risk_per_trade_pct"], p["max_position_pct"]


def _stop_pct(symbol, asset_type, sl_params):
    """Resolve the stop % for a symbol: per-symbol (e.g. gold) -> per-type
    (e.g. forex) -> default. All UI-tunable in the stop_loss config."""
    by_symbol = sl_params.get("by_symbol") or {}
    if symbol in by_symbol:
        return float(by_symbol[symbol])
    by_type = sl_params.get("by_type") or {}
    if asset_type in by_type:
        return float(by_type[asset_type])
    return float(sl_params.get("pct", 6.0))


def _latest_price(asset, db):
    tcfg = db.query(SourceConfig).filter(SourceConfig.source == "technical").first()
    exch = tcfg.provider if tcfg else None
    atype = assets.type_of(asset, db)
    try:
        data = get_ohlcv(
            asset, asset_type=atype, exchange=exch, timeframe="1h", limit=3,
            api_key=twelvedata.get_key(db) if atype == "forex" else None,
        )
    except Exception:
        return None
    if data is None or data.empty:
        return None
    return float(data["Close"].iloc[-1])


def _position_pnl(trade, price):
    if trade.side == "short":
        return (trade.entry_price - price) * trade.size
    return (price - trade.entry_price) * trade.size


# --- engine steps -----------------------------------------------------------

def manage_open_positions(db, cfg_map, price_fn=None):
    price_fn = price_fn or (lambda a: _latest_price(a, db))
    closed = []
    for t in db.query(ExecutedTrade).filter(ExecutedTrade.status == "open").all():
        price = price_fn(t.asset)
        if price is None:
            continue
        sl_en, _ = resolve(cfg_map, "stop_loss", t)
        tp_en, _ = resolve(cfg_map, "take_profit", t)
        hit = None
        if t.side == "short":
            if sl_en and t.stop_loss is not None and price >= t.stop_loss:
                hit = "stop"
            elif tp_en and t.take_profit is not None and price <= t.take_profit:
                hit = "target"
        else:  # long
            if sl_en and t.stop_loss is not None and price <= t.stop_loss:
                hit = "stop"
            elif tp_en and t.take_profit is not None and price >= t.take_profit:
                hit = "target"
        if hit:
            t.exit_price = round(price, 6)
            t.pnl = round(_position_pnl(t, price), 4)
            t.status = "closed"
            t.close_reason = hit
            t.exit_time = datetime.datetime.utcnow()
            closed.append(t)
    db.commit()
    return closed


def compute_equity(db, capital, price_fn=None):
    price_fn = price_fn or (lambda a: _latest_price(a, db))
    realized = sum(t.pnl or 0.0 for t in db.query(ExecutedTrade).filter(ExecutedTrade.status == "closed").all())
    unreal = 0.0
    for t in db.query(ExecutedTrade).filter(ExecutedTrade.status == "open").all():
        p = price_fn(t.asset)
        if p is not None:
            unreal += _position_pnl(t, p)
    return capital + realized + unreal, realized, unreal


def update_state(db, state, equity):
    today = datetime.datetime.utcnow().date().isoformat()
    if state.day_date != today:
        state.day_date = today
        state.day_start_equity = equity
    if state.peak_equity is None or equity > state.peak_equity:
        state.peak_equity = equity
    db.commit()


def _daily_realized_pnl(db):
    today = datetime.datetime.utcnow().date()
    total = 0.0
    for t in db.query(ExecutedTrade).filter(ExecutedTrade.status == "closed").all():
        if t.exit_time and t.exit_time.date() == today:
            total += t.pnl or 0.0
    return total


def check_halt(db, cfg_map, equity, capital, state):
    reasons = []
    if state.manual_halt:
        reasons.append("manual_halt")
    dl_en, dl_p = resolve(cfg_map, "daily_loss")
    if dl_en:
        loss = _daily_realized_pnl(db)
        limit = -abs(dl_p["limit_pct"]) / 100.0 * capital
        if loss <= limit:
            reasons.append(f"daily_loss ({loss:.0f} ≤ {limit:.0f})")
    dd_en, dd_p = resolve(cfg_map, "drawdown")
    if dd_en and state.peak_equity:
        dd = (state.peak_equity - equity) / state.peak_equity
        if dd >= dd_p["limit_pct"] / 100.0:
            reasons.append(f"drawdown ({dd * 100:.1f}%)")
    return reasons


def open_new_positions(db, cfg_map, capital, halted_reasons, price_fn=None):
    if halted_reasons:
        return []  # any active breaker blocks ALL new opens
    price_fn = price_fn or (lambda a: _latest_price(a, db))

    _, risk_pct, max_pos_pct = _account(cfg_map)
    mc_en, mc_p = resolve(cfg_map, "max_concurrent")

    open_trades = db.query(ExecutedTrade).filter(ExecutedTrade.status == "open").all()
    open_assets = {t.asset for t in open_trades}
    open_count = len(open_trades)

    opened = []
    seen = set()
    pendings = (
        db.query(TradingSignal)
        .filter(TradingSignal.status == "pending")
        .order_by(TradingSignal.timestamp.desc())
        .all()
    )
    for sig in pendings:
        if sig.asset in seen:
            continue
        seen.add(sig.asset)
        if sig.asset in open_assets:
            continue  # one open position per asset
        if sig.direction not in ("bullish", "bearish"):
            continue
        if mc_en and open_count >= mc_p["max"]:
            break  # concurrency cap reached

        price = price_fn(sig.asset)
        if price is None:
            continue
        side = "long" if sig.direction == "bullish" else "short"

        sl_en, sl_p = resolve(cfg_map, "stop_loss")
        tp_en, tp_p = resolve(cfg_map, "take_profit")
        stop_pct = _stop_pct(sig.asset, assets.type_of(sig.asset, db), sl_p) / 100.0
        rr = tp_p["rr"]
        risk_amount = risk_pct / 100.0 * capital
        cap_notional = max_pos_pct / 100.0 * capital

        if sl_en and stop_pct > 0:
            stop_dist = price * stop_pct
            size = risk_amount / stop_dist
        else:
            stop_dist = price * stop_pct  # nominal, for target spacing
            size = cap_notional / price
        if size * price > cap_notional:
            size = cap_notional / price

        if sl_en:
            stop = price - stop_dist if side == "long" else price + stop_dist
        else:
            stop = None
        t_dist = stop_dist * rr
        target = (price + t_dist if side == "long" else price - t_dist) if tp_en else None

        trade = ExecutedTrade(
            signal_id=sig.id, asset=sig.asset, side=side,
            entry_price=round(price, 6), size=round(size, 8),
            stop_loss=round(stop, 6) if stop is not None else None,
            take_profit=round(target, 6) if target is not None else None,
            status="open", entry_time=datetime.datetime.utcnow(), overrides=None,
        )
        db.add(trade)
        opened.append(trade)
        open_count += 1
        open_assets.add(sig.asset)
    db.commit()
    return opened


def run_risk_engine(db: Session, price_fn=None):
    cfg_map = _config_map(db)
    capital, _, _ = _account(cfg_map)
    state = _get_state(db)

    # Per-tick price cache: fetch each symbol's price once (manage + equity +
    # open all reuse it). Important for the Twelve Data free-tier forex budget.
    if price_fn is None:
        _cache = {}

        def price_fn(asset):
            if asset not in _cache:
                _cache[asset] = _latest_price(asset, db)
            return _cache[asset]

    from app.services import alerts

    closed = manage_open_positions(db, cfg_map, price_fn=price_fn)
    for t in closed:
        if t.close_reason in ("stop", "target"):
            alerts.exit_hit(t, db)

    equity, realized, unreal = compute_equity(db, capital, price_fn=price_fn)
    update_state(db, state, equity)

    halt = check_halt(db, cfg_map, equity, capital, state)
    # Edge-trigger the breaker alert: fire once when a (new) halt engages, clear
    # when it lifts — not every 5-min tick while halted.
    halt_sig = ";".join(sorted(halt)) if halt else ""
    if halt_sig and halt_sig != (state.halt_alerted or ""):
        alerts.breaker_fired(halt, equity, db)
        state.halt_alerted = halt_sig
        db.commit()
    elif not halt_sig and state.halt_alerted:
        state.halt_alerted = None
        db.commit()

    opened = open_new_positions(db, cfg_map, capital, halt, price_fn=price_fn)
    for t in opened:
        alerts.position_opened(t, db)

    return {
        "equity": round(equity, 2),
        "realized": round(realized, 2),
        "unrealized": round(unreal, 2),
        "peak_equity": round(state.peak_equity, 2) if state.peak_equity else None,
        "halted": halt,
        "closed": len(closed),
        "opened": len(opened),
    }
