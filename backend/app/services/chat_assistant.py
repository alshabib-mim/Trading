"""Claude chat assistant — read-first Q&A over the live trading system, with a
single action path that goes through the chat_actions enforcer (never direct).

Sonnet, with a compact per-message context snapshot (no web_search, no unbounded
tool calls) to keep cost low. The model's ONLY tool is propose_config_change,
which stages a change for explicit user confirmation — it cannot apply anything.
"""
import os

import anthropic
from sqlalchemy.orm import Session

from app.models.models import (
    TradingSignal, ExecutedTrade, SentimentScore, MacroBias, AssetConfig,
    RiskConfig, SourceConfig, AlertConfig,
)
from app.services import chat_actions

DEFAULT_MODEL = "claude-sonnet-4-6"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


INSTRUCTIONS = (
    "You are the assistant for the owner's personal AI trading system (paper-trading only — "
    "no real money). You can READ and EXPLAIN everything in the snapshot below: current signals "
    "and why each is armed or watching, open paper positions, P&L, trade history, and the "
    "sentiment and macro reads. Answer in plain language about THEIR actual system.\n\n"
    "Default mode is read/explain/analyze — you change nothing.\n\n"
    "You may PROPOSE limited, reversible config changes (enable/disable a data source, adjust a "
    "non-safety parameter like risk_per_trade_pct or a stop %, toggle an alert event) by calling "
    "the propose_config_change tool. You do NOT apply changes — the tool only stages a proposal "
    "that the owner must explicitly confirm with the exact before→after diff. Never claim a change "
    "is done; say you've prepared it for confirmation.\n\n"
    "Some things are HARD-WALLED and you must refuse (they are UI-only safety/money controls): the "
    "circuit breakers (daily loss, drawdown, max-concurrent), the manual halt, account starting "
    "capital, API keys / the Telegram token, and anything touching real-money or broker execution. "
    "If asked to change any of these, explain plainly that it's a safety control you cannot touch "
    "from chat. (The server enforces this regardless, but don't pretend you can do it.)\n\n"
    "Be concise and specific. Use the real numbers from the snapshot."
)

PROPOSE_TOOL = {
    "name": "propose_config_change",
    "description": (
        "Stage a single reversible config change for the owner to confirm. Does NOT apply it. "
        "Use the exact dotted target path, e.g. 'risk_config.account.risk_per_trade_pct', "
        "'source_config.macro.enabled', 'alert_config.events.exit_hit', "
        "'risk_config.stop_loss.by_type.forex', 'asset_config.SOL-USD.enabled'. The server "
        "validates and reads the real current value; if the target is walled or invalid it is rejected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "dotted target path of the field to change"},
            "new_value": {"description": "the proposed new value (number, boolean, or string)"},
            "rationale": {"type": "string", "description": "one short sentence on why"},
        },
        "required": ["target", "new_value"],
    },
}


def _flags(sig):
    on = []
    for attr, lbl in (("technical_conf", "tech"), ("whale_conf", "whale"), ("sentiment_conf", "sent"),
                      ("institutional_conf", "13F"), ("news_conf", "news")):
        if getattr(sig, attr, None):
            on.append(lbl)
    return ",".join(on) or "none"


def build_context(db: Session) -> str:
    """A compact snapshot of the live system. Kept small on purpose (cost)."""
    lines = []

    # Latest signal per asset.
    types = {a.symbol: a.asset_type for a in db.query(AssetConfig).all()}
    rows = db.query(TradingSignal).order_by(TradingSignal.timestamp.desc()).limit(200).all()
    latest = {}
    for r in rows:
        if r.asset not in latest:
            latest[r.asset] = r
    lines.append("SIGNALS (latest per asset):")
    for a in sorted(latest):
        s = latest[a]
        line = (f"  {a} [{types.get(a,'?')}] {s.direction or 'none'} · {s.status} · "
                f"conf {round((s.confidence_score or 0)*100)}% · confirms: {_flags(s)}")
        if s.status == "pending" and s.reasoning:
            line += f" · why: {s.reasoning[:160]}"
        lines.append(line)

    # Positions + P&L.
    opens = db.query(ExecutedTrade).filter(ExecutedTrade.status == "open").all()
    closed = db.query(ExecutedTrade).filter(ExecutedTrade.status == "closed").all()
    realized = sum(t.pnl or 0.0 for t in closed)
    wins = sum(1 for t in closed if (t.pnl or 0) > 0)
    lines.append(f"\nOPEN POSITIONS ({len(opens)}):")
    for t in opens:
        lines.append(f"  {t.asset} {t.side} entry {t.entry_price} size {t.size} "
                     f"stop {t.stop_loss} target {t.take_profit}")
    if not opens:
        lines.append("  (none)")
    lines.append(f"\nREALIZED P&L: ${realized:,.2f} over {len(closed)} closed "
                 f"({wins} wins, {len(closed)-wins} losses). "
                 "Open positions are not marked-to-market in this snapshot.")
    lines.append("RECENT CLOSED TRADES:")
    for t in sorted(closed, key=lambda x: x.exit_time or x.entry_time, reverse=True)[:10]:
        lines.append(f"  {t.asset} {t.side} entry {t.entry_price} exit {t.exit_price} "
                     f"pnl ${t.pnl or 0:,.2f} ({t.close_reason})")

    # Sentiment (stocks).
    sent = db.query(SentimentScore).order_by(SentimentScore.timestamp.desc()).limit(60).all()
    seen = {}
    for s in sent:
        if s.asset not in seen:
            seen[s.asset] = s
    if seen:
        lines.append("\nSENTIMENT (latest per stock):")
        for a in sorted(seen):
            s = seen[a]
            lines.append(f"  {a} score {s.score} — {(s.rationale or '')[:120]}")

    # Macro.
    macro = db.query(MacroBias).order_by(MacroBias.timestamp.desc()).first()
    if macro:
        cur = ", ".join(f"{k}:{v.get('bias')}({v.get('strength')})" for k, v in (macro.currencies or {}).items())
        gold = (macro.gold or {})
        lines.append(f"\nMACRO (latest, {macro.timestamp:%Y-%m-%d %H:%M} UTC): {cur}"
                     f" | GOLD:{gold.get('direction')}({gold.get('strength')})")

    # Risk + alert config summary (read-only context).
    rc = {r.key: (r.params or {}, r.enabled) for r in db.query(RiskConfig).all()}
    if rc:
        acct = rc.get("account", ({}, True))[0]
        lines.append("\nRISK CONFIG: "
                     f"risk_per_trade {acct.get('risk_per_trade_pct')}% · "
                     f"max_position {acct.get('max_position_pct')}% · "
                     f"stop {rc.get('stop_loss',({},1))[0].get('pct')}% · "
                     f"tp_rr {rc.get('take_profit',({},1))[0].get('rr')} · "
                     f"[breakers — UI only] daily_loss {rc.get('daily_loss',({},1))[0].get('limit_pct')}% "
                     f"drawdown {rc.get('drawdown',({},1))[0].get('limit_pct')}% "
                     f"max_concurrent {rc.get('max_concurrent',({},1))[0].get('max')}")
    srcs = {s.source: s.enabled for s in db.query(SourceConfig).all()}
    lines.append("SOURCES enabled: " + ", ".join(f"{k}={'on' if v else 'off'}" for k, v in sorted(srcs.items())))
    ac = db.query(AlertConfig).first()
    if ac:
        lines.append(f"ALERTS: {'on' if ac.enabled else 'off'} · events {ac.events}")

    return "\n".join(lines)


def chat(messages, db: Session, username: str, model: str = None):
    """One assistant turn. Returns {reply, proposal}. proposal is the staged
    confirmation card (or None). The model can only PROPOSE via the enforcer."""
    model = model or DEFAULT_MODEL
    context = build_context(db)
    system = [
        {"type": "text", "text": INSTRUCTIONS, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "CURRENT SYSTEM SNAPSHOT\n" + context},
    ]
    client = _get_client()
    convo = list(messages)
    resp = client.messages.create(
        model=model, max_tokens=1024, system=system, tools=[PROPOSE_TOOL], messages=convo,
    )

    proposal = None
    if resp.stop_reason == "tool_use":
        tool_results = []
        for block in resp.content:
            if getattr(block, "type", "") == "tool_use" and block.name == "propose_config_change":
                inp = block.input or {}
                try:
                    p = chat_actions.propose(db, username, inp.get("target", ""), inp.get("new_value"))
                    if proposal is None:
                        proposal = p
                    note = f" NOTE: {p['risk_note']}." if p.get("risk_note") else ""
                    result = (f"Staged for confirmation — {p['label']}: {p['before']} → {p['after']}.{note} "
                              "Tell the owner you've prepared it and it needs their explicit confirmation.")
                except chat_actions.Rejection as exc:
                    kind = "WALLED safety control" if exc.walled else "rejected"
                    result = f"{kind}: {exc.message}. Explain to the owner you cannot make this change from chat."
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        convo.append({"role": "assistant", "content": resp.content})
        convo.append({"role": "user", "content": tool_results})
        resp = client.messages.create(
            model=model, max_tokens=1024, system=system, tools=[PROPOSE_TOOL], messages=convo,
        )

    reply = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    return {"reply": reply.strip(), "proposal": proposal}
