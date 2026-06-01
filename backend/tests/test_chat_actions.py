"""Chat-action enforcer tests — the security boundary.

The headline checks (user's explicit requirement): telling the assistant to
disable a circuit breaker or lift the manual halt is REFUSED SERVER-SIDE — the
proposal is rejected by chat_actions.propose, never staged, never applied — and
the same target is re-rejected at confirm time even if a row is forged.
"""
import datetime
import json

import pytest
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.models import (
    Base, RiskConfig, SourceConfig, AlertConfig, AssetConfig, ChatAction,
)
from app.services import chat_actions, chat_assistant


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    s = sessionmaker(bind=eng)()
    _seed(s)
    yield s
    s.close()


def _seed(db):
    db.add_all([
        RiskConfig(key="account", enabled=True,
                   params={"starting_capital": 100000.0, "risk_per_trade_pct": 1.0, "max_position_pct": 5.0}),
        RiskConfig(key="daily_loss", enabled=True, params={"limit_pct": 2.0}),
        RiskConfig(key="drawdown", enabled=True, params={"limit_pct": 10.0}),
        RiskConfig(key="max_concurrent", enabled=True, params={"max": 5}),
        RiskConfig(key="stop_loss", enabled=True,
                   params={"pct": 6.0, "by_type": {"forex": 1.0}, "by_symbol": {"XAU-USD": 2.5}}),
        RiskConfig(key="take_profit", enabled=True, params={"rr": 2.5}),
        SourceConfig(source="macro", provider="claude_websearch", enabled=False,
                     options={"max_uses": 12, "model": "claude-sonnet-4-6"}),
        SourceConfig(source="fusion", provider="builtin", enabled=True,
                     options={"arm_threshold": 0.6, "w_news": 0.15}),
        SourceConfig(source="whale", provider="whale_alert", enabled=False, credentials_encrypted="x"),
        SourceConfig(source="technical", provider="kraken", enabled=True),
        AlertConfig(channel="telegram", enabled=False,
                    events={"signal_armed": True, "position_opened": True, "exit_hit": True, "breaker": True}),
        AssetConfig(symbol="SOL-USD", asset_type="crypto", enabled=True),
    ])
    db.commit()


def _risk(db, key, field):
    return (db.query(RiskConfig).filter(RiskConfig.key == key).first().params or {}).get(field)


# ---- THE WALLS: refused server-side ----------------------------------------

WALLED = [
    "risk_config.daily_loss.limit_pct",
    "risk_config.daily_loss.enabled",
    "risk_config.drawdown.limit_pct",
    "risk_config.max_concurrent.max",
    "risk_state.manual_halt",
    "risk_config.account.starting_capital",
    "alert_config.bot_token",
    "source_config.whale.credential",
    "source_config.macro.options.api_key",
    "broker.execution.enabled",
    "execution.live",
    "source_config.fusion.enabled",
]


@pytest.mark.parametrize("target", WALLED)
def test_walled_targets_are_rejected_and_audited(db, target):
    before_breaker = _risk(db, "daily_loss", "limit_pct")
    with pytest.raises(chat_actions.Rejection) as ei:
        chat_actions.propose(db, "owner", target, 999)
    assert ei.value.walled is True
    # nothing changed, and a rejected audit row was written
    assert _risk(db, "daily_loss", "limit_pct") == before_breaker
    row = db.query(ChatAction).filter(ChatAction.target == target).first()
    assert row is not None and row.status == "rejected"


def test_disable_breaker_phrasing_is_refused(db):
    # The literal "disable the daily-loss breaker" intent → enabled=false on the breaker.
    with pytest.raises(chat_actions.Rejection) as ei:
        chat_actions.propose(db, "owner", "risk_config.daily_loss.enabled", False)
    assert ei.value.walled
    assert db.query(RiskConfig).filter(RiskConfig.key == "daily_loss").first().enabled is True


def test_unknown_target_default_denied(db):
    with pytest.raises(chat_actions.Rejection) as ei:
        chat_actions.propose(db, "owner", "risk_config.account.some_made_up_field", 1)
    assert ei.value.walled is False
    assert db.query(ChatAction).filter(ChatAction.status == "rejected").count() >= 1


def test_confirm_re_rejects_a_forged_walled_row(db):
    # Defense in depth: even if a 'proposed' row for a walled target is forged into
    # the table, confirm() re-classifies and refuses to apply.
    forged = ChatAction(action_id="forged1", username="owner",
                        target="risk_config.daily_loss.limit_pct",
                        before_value=json.dumps(2.0), after_value=json.dumps(99.0),
                        status="proposed", created_at=datetime.datetime.utcnow())
    db.add(forged); db.commit()
    with pytest.raises(chat_actions.Rejection) as ei:
        chat_actions.confirm(db, "owner", "forged1", "confirm")
    assert ei.value.walled
    assert _risk(db, "daily_loss", "limit_pct") == 2.0  # unchanged


# ---- ALLOWED: propose → confirm → apply ------------------------------------

def test_allowed_risk_per_trade_full_cycle(db):
    p = chat_actions.propose(db, "owner", "risk_config.account.risk_per_trade_pct", 0.5)
    assert p["before"] == 1.0 and p["after"] == 0.5 and p["risk_note"] is None
    assert _risk(db, "account", "risk_per_trade_pct") == 1.0  # not applied yet

    res = chat_actions.confirm(db, "owner", p["action_id"], "confirm")
    assert res["status"] == "applied" and res["after"] == 0.5
    assert _risk(db, "account", "risk_per_trade_pct") == 0.5  # applied
    row = db.query(ChatAction).filter(ChatAction.action_id == p["action_id"]).first()
    assert row.status == "applied"


def test_cancel_does_not_apply(db):
    p = chat_actions.propose(db, "owner", "risk_config.account.risk_per_trade_pct", 0.5)
    res = chat_actions.confirm(db, "owner", p["action_id"], "cancel")
    assert res["status"] == "cancelled"
    assert _risk(db, "account", "risk_per_trade_pct") == 1.0


def test_stale_write_guard(db):
    p = chat_actions.propose(db, "owner", "risk_config.account.risk_per_trade_pct", 0.5)
    # Value changes out-of-band (e.g. owner edits in the UI) before confirm.
    chat_actions.classify("risk_config.account.risk_per_trade_pct")[1].apply(db, 0.8)
    with pytest.raises(chat_actions.Rejection, match="changed since"):
        chat_actions.confirm(db, "owner", p["action_id"], "confirm")
    assert _risk(db, "account", "risk_per_trade_pct") == 0.8  # not overwritten to 0.5


def test_range_validation(db):
    with pytest.raises(chat_actions.Rejection, match="above the maximum"):
        chat_actions.propose(db, "owner", "risk_config.account.risk_per_trade_pct", 999)
    with pytest.raises(chat_actions.Rejection, match="above the maximum"):
        chat_actions.propose(db, "owner", "source_config.fusion.options.arm_threshold", 2.0)


def test_risk_note_on_widening_stop_and_sizing_increase(db):
    wider = chat_actions.propose(db, "owner", "risk_config.stop_loss.by_type.forex", 3.0)  # 1.0 → 3.0
    assert "INCREASES per-trade risk" in (wider["risk_note"] or "")
    tighter = chat_actions.propose(db, "owner", "risk_config.stop_loss.pct", 4.0)  # 6.0 → 4.0
    assert tighter["risk_note"] is None
    bigger = chat_actions.propose(db, "owner", "risk_config.account.max_position_pct", 8.0)  # 5 → 8
    assert "increases max position size" in (bigger["risk_note"] or "")


def test_allowed_toggles(db):
    # source enable, alert event toggle, asset toggle all work end to end.
    for target, newval, check in [
        ("source_config.macro.enabled", True,
         lambda: db.query(SourceConfig).filter(SourceConfig.source == "macro").first().enabled),
        ("alert_config.events.exit_hit", False,
         lambda: db.query(AlertConfig).first().events["exit_hit"]),
        ("asset_config.SOL-USD.enabled", False,
         lambda: db.query(AssetConfig).filter(AssetConfig.symbol == "SOL-USD").first().enabled),
    ]:
        p = chat_actions.propose(db, "owner", target, newval)
        chat_actions.confirm(db, "owner", p["action_id"], "confirm")
        assert check() == newval


def test_already_set_is_rejected(db):
    with pytest.raises(chat_actions.Rejection, match="already"):
        chat_actions.propose(db, "owner", "risk_config.account.risk_per_trade_pct", 1.0)


# ---- model dispatch (mocked Anthropic client) ------------------------------

def _fake_client(responses):
    """A stand-in Anthropic client returning queued responses from messages.create."""
    seq = iter(responses)

    class _Msgs:
        def create(self, **kwargs):
            return next(seq)
    return SimpleNamespace(messages=_Msgs())


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(target, new_value):
    return SimpleNamespace(type="tool_use", name="propose_config_change", id="tu1",
                           input={"target": target, "new_value": new_value})


def test_chat_walled_request_refused_end_to_end(db, monkeypatch):
    # Model tries to disable the breaker; server refuses; no proposal, breaker intact.
    r1 = SimpleNamespace(stop_reason="tool_use", content=[_tool("risk_config.daily_loss.enabled", False)])
    r2 = SimpleNamespace(stop_reason="end_turn", content=[_text("That's a safety control I can't change from chat.")])
    monkeypatch.setattr(chat_assistant, "_get_client", lambda: _fake_client([r1, r2]))

    out = chat_assistant.chat([{"role": "user", "content": "disable the daily loss breaker"}], db, "owner")
    assert out["proposal"] is None
    assert db.query(RiskConfig).filter(RiskConfig.key == "daily_loss").first().enabled is True
    assert db.query(ChatAction).filter(ChatAction.target == "risk_config.daily_loss.enabled",
                                       ChatAction.status == "rejected").count() == 1


def test_chat_allowed_request_returns_proposal_not_applied(db, monkeypatch):
    r1 = SimpleNamespace(stop_reason="tool_use", content=[_tool("risk_config.account.risk_per_trade_pct", 0.5)])
    r2 = SimpleNamespace(stop_reason="end_turn", content=[_text("Prepared — confirm the change to apply it.")])
    monkeypatch.setattr(chat_assistant, "_get_client", lambda: _fake_client([r1, r2]))

    out = chat_assistant.chat([{"role": "user", "content": "halve my per-trade risk"}], db, "owner")
    assert out["proposal"]["before"] == 1.0 and out["proposal"]["after"] == 0.5
    assert _risk(db, "account", "risk_per_trade_pct") == 1.0  # staged, NOT applied
    row = db.query(ChatAction).filter(ChatAction.action_id == out["proposal"]["action_id"]).first()
    assert row.status == "proposed"
