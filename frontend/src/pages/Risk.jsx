import React, { useState, useEffect } from 'react';
import api from '../api';

const LABELS = {
  account: 'Account',
  daily_loss: 'Daily loss limit',
  drawdown: 'Drawdown halt',
  max_concurrent: 'Max concurrent positions',
  stop_loss: 'Stop-loss (default)',
  take_profit: 'Take-profit (default)',
};
const PARAM_LABELS = {
  starting_capital: 'Starting capital ($)',
  risk_per_trade_pct: 'Risk per trade (%)',
  max_position_pct: 'Max position (% notional)',
  limit_pct: 'Limit (%)',
  max: 'Max positions',
  pct: 'Stop (%)',
  rr: 'Reward : risk (×)',
};
// account has no on/off (it's not a guardrail); everything else is toggleable.
const TOGGLEABLE = new Set(['daily_loss', 'drawdown', 'max_concurrent', 'stop_loss', 'take_profit']);

function fieldsFromRow(row) {
  const f = {};
  Object.keys(row.params || {}).forEach((k) => {
    f[k] = row.params[k] == null ? '' : String(row.params[k]);
  });
  return f;
}

function ConfigCard({ row, onSaved, onChanged }) {
  const [enabled, setEnabled] = useState(row.enabled);
  const [fields, setFields] = useState(() => fieldsFromRow(row));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  // Re-sync from props when the row actually changes (e.g. after a save).
  // The 30s state poll does NOT touch rows, so in-progress edits are preserved.
  useEffect(() => {
    setEnabled(row.enabled);
    setFields(fieldsFromRow(row));
  }, [row.key, row.updated_at]);

  const setField = (k, val) => setFields((f) => ({ ...f, [k]: val }));

  const save = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const params = {};
      Object.entries(fields).forEach(([k, v]) => {
        params[k] = String(v).trim() === '' ? null : Number(v);
      });
      const res = await api.put(`/risk/config/${row.key}`, { enabled, params });
      setMsg({ kind: 'ok', text: 'Saved' });
      if (onSaved) onSaved(res.data);
      if (onChanged) onChanged();
    } catch (e) {
      setMsg({ kind: 'error', text: e.response?.data?.detail || 'Save failed' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card risk-card">
      <div className="source-head">
        <h2>{LABELS[row.key] || row.key}</h2>
        {TOGGLEABLE.has(row.key) ? (
          <label className="checkbox">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> enabled
          </label>
        ) : (
          <span className="badge">always on</span>
        )}
      </div>
      <div className="row3">
        {Object.keys(fields).map((k) => (
          <label key={k}>
            {PARAM_LABELS[k] || k}
            <input
              type="text"
              inputMode="decimal"
              value={fields[k]}
              onChange={(e) => setField(k, e.target.value)}
            />
          </label>
        ))}
      </div>
      <div className="source-foot">
        <button onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        {msg && <span className={msg.kind === 'ok' ? 'ok' : 'error'}>{msg.text}</span>}
      </div>
    </section>
  );
}

export default function Risk() {
  const [rows, setRows] = useState([]);
  const [state, setState] = useState(null);
  const [error, setError] = useState('');

  const loadState = async () => {
    try {
      const s = await api.get('/risk/state');
      setState(s.data);
    } catch { /* ignore */ }
  };

  const load = async () => {
    try {
      const [c, s] = await Promise.all([api.get('/risk/config'), api.get('/risk/state')]);
      setRows(c.data);
      setState(s.data);
      setError('');
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load risk config');
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(loadState, 30000);
    return () => clearInterval(t);
  }, []);

  const toggleHalt = async () => {
    if (!state) return;
    try {
      await api.put('/risk/state', { manual_halt: !state.manual_halt });
      loadState();
    } catch {
      setError('Halt toggle failed');
    }
  };

  const onSaved = (u) => setRows((rs) => rs.map((r) => (r.key === u.key ? u : r)));
  const money = (v) => (v == null ? '—' : `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);

  return (
    <div className="page">
      <h1>Risk & Paper Execution</h1>
      <p className="section-sub">
        Paper mode — no broker, no real money. Daily-loss, drawdown and max-concurrent are
        global circuit breakers (on/off). Stop-loss & take-profit are global defaults, overridable
        per trade on the dashboard. Changes take effect on the next 5-min risk tick.
      </p>
      {error && <div className="error">{error}</div>}

      {state && (
        <section className="card risk-state">
          <div className="rs-grid">
            <div><span className="rs-l">Equity</span><span className="rs-v">{money(state.equity)}</span></div>
            <div><span className="rs-l">Peak</span><span className="rs-v">{money(state.peak_equity)}</span></div>
            <div><span className="rs-l">Drawdown</span><span className="rs-v">{state.drawdown_pct}%</span></div>
            <div><span className="rs-l">Realized P&L</span><span className={`rs-v ${state.realized_pnl >= 0 ? 'pos' : 'neg'}`}>{money(state.realized_pnl)}</span></div>
            <div><span className="rs-l">Today P&L</span><span className={`rs-v ${state.daily_pnl >= 0 ? 'pos' : 'neg'}`}>{money(state.daily_pnl)}</span></div>
            <div><span className="rs-l">Status</span><span className={`rs-v ${state.halted ? 'neg' : 'pos'}`}>{state.halted ? 'HALTED' : 'active'}</span></div>
          </div>
          {state.halt_reasons && state.halt_reasons.length > 0 && (
            <div className="rs-reasons">halt: {state.halt_reasons.join(' · ')}</div>
          )}
          <button className={`link-btn ${state.manual_halt ? 'danger' : ''}`} onClick={toggleHalt}>
            {state.manual_halt ? 'Clear manual halt' : 'Manual halt (kill switch)'}
          </button>
        </section>
      )}

      <div className="grid">
        {rows.map((r) => <ConfigCard key={r.key} row={r} onSaved={onSaved} onChanged={loadState} />)}
      </div>
    </div>
  );
}
