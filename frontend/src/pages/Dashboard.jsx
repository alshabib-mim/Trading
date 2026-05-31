import React, { useState, useEffect } from 'react';
import api from '../api';

const ASSETS = ['AAPL', 'TSLA', 'BTC-USD', 'ETH-USD'];
const CRYPTO = new Set(['BTC-USD', 'ETH-USD']);
const ARM_THRESHOLD = 0.6;
const REFRESH_MS = 30000;

const FLAGS = [
  { key: 'whale_conf', label: 'Whale' },
  { key: 'technical_conf', label: 'Tech' },
  { key: 'sentiment_conf', label: 'Sent' },
  { key: 'institutional_conf', label: '13F' },
];

function dirClass(d) {
  return d === 'bullish' ? 'dir-bull' : d === 'bearish' ? 'dir-bear' : 'dir-none';
}

function fmtTime(ts) {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function EngineRow({ asset, sig }) {
  const dirSrc = CRYPTO.has(asset) ? 'whale flow' : 'insider (Form 4)';
  if (!sig) {
    return (
      <div className="engine-row">
        <div className="er-head">
          <span className="er-asset">{asset}</span>
          <span className="muted">no read yet</span>
        </div>
      </div>
    );
  }
  const conf = (sig.confidence_score || 0) * 100;
  const armed = sig.status === 'pending';
  return (
    <div className={`engine-row ${armed ? 'armed' : ''}`}>
      <div className="er-head">
        <span className="er-asset">{asset}</span>
        <span className={`badge dir ${dirClass(sig.direction)}`}>{sig.direction || 'none'}</span>
        <span className={`badge status ${armed ? 'st-armed' : 'st-watch'}`}>{sig.status}</span>
        <span className="spacer" />
        <span className="muted small">dir: {dirSrc}</span>
        <span className="muted small">{fmtTime(sig.timestamp)}</span>
      </div>

      <div className="conf-row">
        <div className="conf-bar" title={`armed-confidence ${conf.toFixed(1)}% · arms at ${ARM_THRESHOLD * 100}%`}>
          <div className={`conf-fill ${armed ? 'armed' : ''}`} style={{ width: `${Math.min(conf, 100)}%` }} />
          <div className="conf-thresh" style={{ left: `${ARM_THRESHOLD * 100}%` }} />
          <span className="conf-val">{conf.toFixed(0)}%</span>
        </div>
        {sig.direction !== 'none' && sig.direction_conviction != null && (
          <span
            className={`dir-conv ${dirClass(sig.direction)}`}
            title="raw strength of the direction source (0–1), before the timing gate"
          >
            {CRYPTO.has(asset) ? 'whale' : 'insider'} {sig.direction_conviction.toFixed(2)}
          </span>
        )}
      </div>

      <div className="flags">
        {FLAGS.map((f) => (
          <span key={f.key} className={`flag ${sig[f.key] ? 'on' : ''}`}>
            {sig[f.key] ? '✓' : '·'} {f.label}
          </span>
        ))}
      </div>

      {armed && sig.reasoning && <div className="er-reasoning">{sig.reasoning}</div>}
    </div>
  );
}

export default function Dashboard() {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchData = async () => {
      try {
        const [sigRes, trRes] = await Promise.all([
          api.get('/signals/'),
          api.get('/trades/'),
        ]);
        if (!alive) return;
        setSignals(sigRes.data);
        setTrades(trRes.data);
        setErr(null);
      } catch (e) {
        if (alive) setErr(e.response?.data?.detail || 'Failed to load');
      }
    };
    fetchData();
    const t = setInterval(fetchData, REFRESH_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // Latest signal per asset (list is newest-first → first hit wins).
  const latest = {};
  for (const s of signals) {
    if (!(s.asset in latest)) latest[s.asset] = s;
  }

  return (
    <div className="page">
      <h1>AI Trading System Dashboard</h1>
      {err && <div className="error">{err}</div>}

      <section className="card">
        <h2>Engine read — current</h2>
        <p className="section-sub">
          A signal <b>arms</b> (pending) only when there is a direction, technical timing
          agrees, and confidence ≥ {ARM_THRESHOLD * 100}%. Otherwise it’s a <b>watch</b> row —
          the engine sees something but the sources haven’t lined up. Lit flags = sources
          that agreed with the read direction.
        </p>
        <div className="engine-list">
          {ASSETS.map((a) => (
            <EngineRow key={a} asset={a} sig={latest[a]} />
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Executed Trades</h2>
        <table>
          <thead>
            <tr>
              <th>Asset</th>
              <th>Entry</th>
              <th>Size</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => (
              <tr key={t.id}>
                <td>{t.asset}</td>
                <td>${t.entry_price.toFixed(2)}</td>
                <td>{t.size}</td>
                <td className="pnl">${t.pnl?.toFixed(2) || '0.00'}</td>
              </tr>
            ))}
            {trades.length === 0 && (
              <tr>
                <td colSpan="4" className="empty">No trades yet</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
