import React, { useState, useRef, useEffect } from 'react';
import api from '../api';

function fmtVal(v) {
  if (v === null || v === undefined) return '(unset)';
  if (typeof v === 'boolean') return v ? 'on' : 'off';
  return String(v);
}

// The confirmation card is rendered from the SERVER's proposal (literal field +
// real before→after), never from the model's prose. The user confirms the exact diff.
function ProposalCard({ proposal, onResolve, busy }) {
  return (
    <div className="proposal-card">
      <div className="proposal-title">Confirm config change</div>
      <div className="proposal-target">{proposal.label} <span className="muted small">({proposal.target})</span></div>
      <div className="proposal-diff">
        <span className="pv-before">{fmtVal(proposal.before)}</span>
        <span className="pv-arrow">→</span>
        <span className="pv-after">{fmtVal(proposal.after)}</span>
      </div>
      {proposal.risk_note && <div className="proposal-risk">⚠ {proposal.risk_note}</div>}
      <div className="proposal-actions">
        <button className="confirm-btn" disabled={busy} onClick={() => onResolve('confirm')}>Confirm</button>
        <button disabled={busy} onClick={() => onResolve('cancel')}>Cancel</button>
      </div>
    </div>
  );
}

export default function Chat() {
  const [messages, setMessages] = useState([]);          // {role, content}
  const [input, setInput] = useState('');
  const [proposal, setProposal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, proposal]);

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setErr(null);
    setProposal(null);
    const next = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setInput('');
    setBusy(true);
    try {
      const { data } = await api.post('/chat/message', { messages: next });
      if (data.reply) setMessages((m) => [...m, { role: 'assistant', content: data.reply }]);
      if (data.proposal) setProposal(data.proposal);
    } catch (e) {
      setErr(e.response?.data?.detail || 'Assistant error');
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (decision) => {
    if (!proposal) return;
    setBusy(true);
    setErr(null);
    try {
      const { data } = await api.post('/chat/confirm', { action_id: proposal.action_id, decision });
      const note = decision === 'cancel'
        ? `Cancelled — ${proposal.label} left unchanged.`
        : `✅ Applied — ${data.label}: ${fmtVal(data.before)} → ${fmtVal(data.after)}.`;
      setMessages((m) => [...m, { role: 'system', content: note }]);
    } catch (e) {
      setMessages((m) => [...m, { role: 'system', content: `Not applied — ${e.response?.data?.detail || 'failed'}.` }]);
    } finally {
      setProposal(null);
      setBusy(false);
    }
  };

  const onKey = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } };

  return (
    <div className="page chat-page">
      <h1>Assistant</h1>
      <p className="section-sub">
        Ask about your live system in plain language — signals and why they armed, open positions,
        P&amp;L, trade history, sentiment and macro. It can also propose limited, reversible config
        changes, which you confirm with the exact before→after diff. Safety controls (circuit
        breakers, manual halt, capital, keys) are not reachable from here.
      </p>
      {err && <div className="error">{err}</div>}

      <div className="chat-log">
        {messages.length === 0 && (
          <div className="chat-empty muted">
            e.g. “Why is EUR-USD only watching?” · “What’s my realized P&amp;L?” · “Halve my per-trade risk.”
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <div className="chat-role">{m.role === 'user' ? 'You' : m.role === 'assistant' ? 'Assistant' : 'System'}</div>
            <div className="chat-content">{m.content}</div>
          </div>
        ))}
        {proposal && <ProposalCard proposal={proposal} onResolve={resolve} busy={busy} />}
        {busy && !proposal && <div className="chat-msg assistant"><div className="chat-content muted">…</div></div>}
        <div ref={endRef} />
      </div>

      <div className="chat-input">
        <textarea
          rows="2" value={input} placeholder="Ask about your system…"
          onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} disabled={busy}
        />
        <button onClick={send} disabled={busy || !input.trim()}>Send</button>
      </div>
    </div>
  );
}
