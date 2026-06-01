"""Server-side action enforcer for the chat assistant.

THE security boundary. The model can only *propose* (target, new_value); this
module decides — never the model — whether a change is allowed, reads the real
current value from the DB, validates type/range, and applies only on an explicit
user confirm with a stale-write guard. Every proposal and outcome is audited.

Three classifications:
  • ALLOWED  — a known, non-safety, reversible field → propose → confirm → apply
  • WALLED   — a safety/money control → rejected with a specific reason, even WITH
               confirmation (UI-only). Enforced here, not by the prompt.
  • UNKNOWN  — anything else → rejected (default-deny).

WALLED set (hard wall, can never be reached through chat):
  • risk_config.daily_loss.*, drawdown.*, max_concurrent.*  (the 3 circuit breakers)
  • risk_config.account.starting_capital  (denominator of the daily-loss limit —
    a backdoor that would weaken the breaker)
  • risk_state.manual_halt                (the kill switch)
  • any credential/secret (API keys, Telegram token/chat id)
  • any broker / real-money execution control (none today; permanently walled for Phase 5)
  • the fusion engine on/off toggle
"""
import json
import uuid
import datetime

from app.models.models import (
    ChatAction, RiskConfig, SourceConfig, AlertConfig, AssetConfig,
)

ACTION_TTL_SECONDS = 600  # a proposal expires after 10 minutes

# Sources whose enable/disable + tuning chat may touch (NOT fusion — engine is UI-only).
TUNABLE_SOURCES = {"technical", "insider", "institutional", "whale", "sentiment", "news", "macro", "forex"}
ALERT_EVENTS = {"signal_armed", "position_opened", "exit_hit", "breaker"}
# Whitelisted option keys per source (anything else under .options is denied).
SOURCE_OPTION_WHITELIST = {
    "fusion": {
        "arm_threshold": ("float", 0.0, 1.0),
        "w_direction": ("float", 0.0, 2.0),
        "w_sentiment": ("float", 0.0, 2.0),
        "w_support": ("float", 0.0, 2.0),
        "w_news": ("float", 0.0, 2.0),
        "reasoning_model": ("str", None, None),
    },
    "macro": {
        "max_uses": ("int", 1, 20),
        "model": ("str", None, None),
        "skip_forex_weekend": ("bool", None, None),
    },
    "sentiment": {"model": ("str", None, None)},
    "insider": {
        "buyer_scale": ("float", 1.0, 100.0),
        "value_scale": ("float", 1.0, 1_000_000_000.0),
    },
}


class Rejection(Exception):
    """A proposal that must not proceed. .walled marks safety-wall refusals."""
    def __init__(self, message, walled=False):
        super().__init__(message)
        self.message = message
        self.walled = walled


# --- coercion helpers -------------------------------------------------------

def _as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false", "on", "off", "yes", "no"):
        return v.strip().lower() in ("true", "on", "yes")
    raise Rejection(f"expected true/false, got {v!r}")


def _as_num(v, lo, hi, integer=False):
    if isinstance(v, bool):
        raise Rejection(f"expected a number, got boolean {v!r}")
    try:
        n = float(v)
    except (TypeError, ValueError):
        raise Rejection(f"expected a number, got {v!r}")
    if integer:
        if n != int(n):
            raise Rejection(f"expected a whole number, got {v!r}")
        n = int(n)
    if lo is not None and n < lo:
        raise Rejection(f"value {n} is below the minimum {lo}")
    if hi is not None and n > hi:
        raise Rejection(f"value {n} is above the maximum {hi}")
    return n


def _as_str(v):
    if not isinstance(v, str) or not v.strip():
        raise Rejection(f"expected a non-empty string, got {v!r}")
    return v.strip()


# --- classification: the whitelist + walls ----------------------------------

class _Spec:
    def __init__(self, label, coerce, read, apply, risk_note=None):
        self.label = label
        self.coerce = coerce
        self.read = read
        self.apply = apply
        self.risk_note = risk_note or (lambda before, after: None)


def _pct_risk_note(noun):
    def note(before, after):
        if before is not None and after is not None and after > before:
            return f"increases {noun}"
        return None
    return note


def _stop_risk_note(before, after):
    if before is not None and after is not None and after > before:
        return "widens the stop — this INCREASES per-trade risk"
    return None


# RiskConfig (key -> params JSON) read/apply ---------------------------------

def _risk_read(key, *path):
    def read(db):
        row = db.query(RiskConfig).filter(RiskConfig.key == key).first()
        node = (row.params if row and row.params else {})
        for p in path:
            if not isinstance(node, dict):
                return None
            node = node.get(p)
        return node
    return read


def _risk_apply(key, *path):
    def apply(db, value):
        row = db.query(RiskConfig).filter(RiskConfig.key == key).first()
        if row is None:
            row = RiskConfig(key=key, enabled=True, params={})
            db.add(row)
        params = json.loads(json.dumps(row.params or {}))  # deep copy
        node = params
        for p in path[:-1]:
            node = node.setdefault(p, {})
        node[path[-1]] = value
        row.params = params  # reassign so SQLAlchemy detects the JSON change
        db.commit()
    return apply


# SourceConfig read/apply (column or options.key) ----------------------------

def _source_col_read(source, col):
    def read(db):
        row = db.query(SourceConfig).filter(SourceConfig.source == source).first()
        return getattr(row, col, None) if row else None
    return read


def _source_col_apply(source, col):
    def apply(db, value):
        row = db.query(SourceConfig).filter(SourceConfig.source == source).first()
        if row is None:
            raise Rejection(f"source '{source}' not found")
        setattr(row, col, value)
        db.commit()
    return apply


def _source_opt_read(source, key):
    def read(db):
        row = db.query(SourceConfig).filter(SourceConfig.source == source).first()
        return (row.options or {}).get(key) if row else None
    return read


def _source_opt_apply(source, key):
    def apply(db, value):
        row = db.query(SourceConfig).filter(SourceConfig.source == source).first()
        if row is None:
            raise Rejection(f"source '{source}' not found")
        opts = json.loads(json.dumps(row.options or {}))
        opts[key] = value
        row.options = opts
        db.commit()
    return apply


def _alert_col_read(col):
    def read(db):
        row = db.query(AlertConfig).first()
        return getattr(row, col, None) if row else None
    return read


def _alert_col_apply(col):
    def apply(db, value):
        row = db.query(AlertConfig).first()
        if row is None:
            raise Rejection("alert config not found")
        setattr(row, col, value)
        db.commit()
    return apply


def _alert_event_read(event):
    def read(db):
        row = db.query(AlertConfig).first()
        evs = (row.events or {}) if row else {}
        return evs.get(event, True)
    return read


def _alert_event_apply(event):
    def apply(db, value):
        row = db.query(AlertConfig).first()
        if row is None:
            raise Rejection("alert config not found")
        evs = json.loads(json.dumps(row.events or {}))
        evs[event] = value
        row.events = evs
        db.commit()
    return apply


def _asset_read(symbol):
    def read(db):
        row = db.query(AssetConfig).filter(AssetConfig.symbol == symbol).first()
        return row.enabled if row else None
    return read


def _asset_apply(symbol):
    def apply(db, value):
        row = db.query(AssetConfig).filter(AssetConfig.symbol == symbol).first()
        if row is None:
            raise Rejection(f"asset '{symbol}' not found")
        row.enabled = value
        db.commit()
    return apply


def _opt_spec(source, key, label):
    typ, lo, hi = SOURCE_OPTION_WHITELIST[source][key]
    if typ == "bool":
        coerce = _as_bool
    elif typ == "str":
        coerce = _as_str
    elif typ == "int":
        coerce = lambda v: _as_num(v, lo, hi, integer=True)  # noqa: E731
    else:
        coerce = lambda v: _as_num(v, lo, hi)  # noqa: E731
    return _Spec(label, coerce, _source_opt_read(source, key), _source_opt_apply(source, key))


def classify(target):
    """Return ('allowed', _Spec) | ('walled', reason) | ('unknown', reason)."""
    parts = (target or "").split(".")
    t = target or ""

    # --- hard walls (checked first; specific reasons) ---
    low = t.lower()
    if "credential" in low or low.endswith(".provider") or "bot_token" in low or "chat_id" in low or "api_key" in low:
        return "walled", "credentials/secrets are UI-only — chat can't read or change keys"
    if parts[0] in ("broker", "execution") or "broker" in low or "execution" in low:
        return "walled", "real-money / broker execution controls are never reachable through chat"
    if parts[0] == "risk_state" and len(parts) >= 2 and parts[1] == "manual_halt":
        return "walled", "the manual halt is a safety kill switch — UI-only"
    if parts[0] == "risk_config" and len(parts) >= 2:
        if parts[1] in ("daily_loss", "drawdown", "max_concurrent"):
            return "walled", f"'{parts[1]}' is a circuit breaker — safety control, UI-only"
        if parts[1] == "account" and len(parts) >= 3 and parts[2] == "starting_capital":
            return "walled", "starting_capital is the daily-loss breaker's denominator — UI-only"
    if parts[0] == "source_config" and len(parts) >= 3 and parts[1] == "fusion" and parts[2] == "enabled":
        return "walled", "the fusion engine on/off toggle is UI-only"

    # --- allowed registry (default-deny: anything not matched is UNKNOWN) ---
    if parts[0] == "risk_config" and len(parts) >= 3:
        key, field = parts[1], parts[2]
        if key == "account" and field == "risk_per_trade_pct":
            return "allowed", _Spec("risk per trade %", lambda v: _as_num(v, 0.01, 10.0),
                                    _risk_read(key, field), _risk_apply(key, field),
                                    _pct_risk_note("per-trade risk"))
        if key == "account" and field == "max_position_pct":
            return "allowed", _Spec("max position %", lambda v: _as_num(v, 0.1, 100.0),
                                    _risk_read(key, field), _risk_apply(key, field),
                                    _pct_risk_note("max position size"))
        if key == "take_profit" and field == "rr":
            return "allowed", _Spec("take-profit RR", lambda v: _as_num(v, 0.1, 20.0),
                                    _risk_read(key, field), _risk_apply(key, field))
        if key == "stop_loss" and field == "pct":
            return "allowed", _Spec("stop-loss %", lambda v: _as_num(v, 0.05, 50.0),
                                    _risk_read(key, "pct"), _risk_apply(key, "pct"), _stop_risk_note)
        if key == "stop_loss" and field == "by_type" and len(parts) == 4:
            atype = parts[3]
            return "allowed", _Spec(f"stop-loss % ({atype})", lambda v: _as_num(v, 0.05, 50.0),
                                    _risk_read(key, "by_type", atype), _risk_apply(key, "by_type", atype),
                                    _stop_risk_note)
        if key == "stop_loss" and field == "by_symbol" and len(parts) == 4:
            sym = parts[3]
            return "allowed", _Spec(f"stop-loss % ({sym})", lambda v: _as_num(v, 0.05, 50.0),
                                    _risk_read(key, "by_symbol", sym), _risk_apply(key, "by_symbol", sym),
                                    _stop_risk_note)

    if parts[0] == "source_config" and len(parts) >= 3:
        source, field = parts[1], parts[2]
        if source in TUNABLE_SOURCES:
            if field == "enabled":
                return "allowed", _Spec(f"{source} enabled", _as_bool,
                                        _source_col_read(source, "enabled"), _source_col_apply(source, "enabled"))
            if field == "weight":
                return "allowed", _Spec(f"{source} weight", lambda v: _as_num(v, 0.0, 5.0),
                                        _source_col_read(source, "weight"), _source_col_apply(source, "weight"))
            if field in ("freshness_seconds", "interval_seconds"):
                return "allowed", _Spec(f"{source} {field}", lambda v: _as_num(v, 10, 1_000_000, integer=True),
                                        _source_col_read(source, field), _source_col_apply(source, field))
        # fusion tuning + per-source options
        if field == "options" and len(parts) == 4:
            okey = parts[3]
            if source in SOURCE_OPTION_WHITELIST and okey in SOURCE_OPTION_WHITELIST[source]:
                return "allowed", _opt_spec(source, okey, f"{source}.{okey}")

    if parts[0] == "alert_config" and len(parts) >= 2:
        if parts[1] == "enabled":
            return "allowed", _Spec("alerts enabled", _as_bool, _alert_col_read("enabled"), _alert_col_apply("enabled"))
        if parts[1] == "events" and len(parts) == 3 and parts[2] in ALERT_EVENTS:
            ev = parts[2]
            return "allowed", _Spec(f"alert: {ev}", _as_bool, _alert_event_read(ev), _alert_event_apply(ev))

    if parts[0] == "asset_config" and len(parts) == 3 and parts[2] == "enabled":
        sym = parts[1]
        return "allowed", _Spec(f"{sym} enabled", _as_bool, _asset_read(sym), _asset_apply(sym))

    return "unknown", "not a permitted action"


# --- audit + lifecycle ------------------------------------------------------

def _audit(db, username, target, label, before, after, status, reason=None, risk_note=None, action_id=None):
    row = ChatAction(
        action_id=action_id or uuid.uuid4().hex,
        username=username, target=target, label=label,
        before_value=None if before is None else json.dumps(before),
        after_value=None if after is None else json.dumps(after),
        status=status, reason=reason, risk_note=risk_note,
        created_at=datetime.datetime.utcnow(),
        resolved_at=datetime.datetime.utcnow() if status != "proposed" else None,
    )
    db.add(row)
    db.commit()
    return row


def propose(db, username, target, new_value):
    """Validate + stage a change. Returns a proposal dict (for the confirmation
    card) or raises Rejection (audited). NEVER applies anything."""
    status, spec = classify(target)
    if status == "walled":
        _audit(db, username, target, None, None, None, "rejected", reason=spec)
        raise Rejection(spec, walled=True)
    if status == "unknown":
        _audit(db, username, target, None, None, None, "rejected", reason=spec)
        raise Rejection(spec)

    try:
        coerced = spec.coerce(new_value)
    except Rejection as exc:
        _audit(db, username, target, spec.label, None, new_value, "rejected", reason=exc.message)
        raise

    current = spec.read(db)
    if current == coerced:
        raise Rejection(f"{spec.label} is already {coerced}")

    note = spec.risk_note(current, coerced)
    row = _audit(db, username, target, spec.label, current, coerced, "proposed", risk_note=note)
    return {
        "action_id": row.action_id,
        "target": target,
        "label": spec.label,
        "before": current,
        "after": coerced,
        "risk_note": note,
    }


def confirm(db, username, action_id, decision):
    """Apply or cancel a staged proposal. Re-validates the wall/allowlist and
    guards against stale writes. Returns a result dict."""
    row = db.query(ChatAction).filter(
        ChatAction.action_id == action_id, ChatAction.status == "proposed"
    ).first()
    if row is None:
        raise Rejection("no pending action with that id")

    age = (datetime.datetime.utcnow() - row.created_at).total_seconds()
    if age > ACTION_TTL_SECONDS:
        row.status = "expired"; row.resolved_at = datetime.datetime.utcnow(); db.commit()
        raise Rejection("this proposal expired — please ask again")

    if decision == "cancel":
        row.status = "cancelled"; row.resolved_at = datetime.datetime.utcnow(); db.commit()
        return {"status": "cancelled", "target": row.target}

    # decision == confirm: re-classify (defense in depth) ...
    status, spec = classify(row.target)
    if status != "allowed":
        row.status = "rejected"; row.reason = f"blocked at apply: {spec}"
        row.resolved_at = datetime.datetime.utcnow(); db.commit()
        raise Rejection(spec, walled=(status == "walled"))

    coerced = spec.coerce(json.loads(row.after_value))
    # ... and guard against a stale write (value changed since we proposed).
    current = spec.read(db)
    if json.dumps(current) != (row.before_value or json.dumps(None)):
        row.status = "stale"; row.reason = "value changed since it was proposed"
        row.resolved_at = datetime.datetime.utcnow(); db.commit()
        raise Rejection("the value changed since this was proposed — please ask again")

    spec.apply(db, coerced)
    row.status = "applied"; row.resolved_at = datetime.datetime.utcnow(); db.commit()
    return {"status": "applied", "target": row.target, "label": row.label,
            "before": current, "after": coerced, "risk_note": row.risk_note}
