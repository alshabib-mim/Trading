import React, { useState, useEffect, useCallback } from 'react';
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

function sentDir(score) {
  if (score == null) return { label: 'neutral', cls: 'dir-none' };
  if (score > 0.5) return { label: 'bullish', cls: 'dir-bull' };
  if (score < 0.5) return { label: 'bearish', cls: 'dir-bear' };
  return { label: 'neutral', cls: 'dir-none' };
}

function NewsCard({ news }) {
  const [open, setOpen] = useState(null);
  const byAsset = {};
  for (const n of news) byAsset[n.asset] = n;

  return (
    <section className="card">
      <h2>News &amp; sentiment</h2>
      <p className="section-sub">
        What the sentiment AI read. Finnhub headlines + Claude’s rationale per stock.
        Sentiment is confirm-only — it nudges confidence, never sets direction.
      </p>
      <div className="engine-list">
        {ASSETS.map((a) => {
          if (CRYPTO.has(a)) {
            return (
              <div key={a} className="engine-row">
                <div className="er-head">
                  <span className="er-asset">{a}</span>
                  <span className="muted small">no news coverage — Finnhub is equities-only; crypto direction comes from whale flow</span>
                </div>
              </div>
            );
          }
          const n = byAsset[a];
          if (!n) {
            return (
              <div key={a} className="engine-row">
                <div className="er-head">
                  <span className="er-asset">{a}</span>
                  <span className="muted small">no sentiment yet — runs hourly when News + Sentiment are enabled</span>
                </div>
              </div>
            );
          }
          const d = sentDir(n.score);
          const isOpen = open === a;
          return (
            <div key={a} className="engine-row">
              <div className="er-head news-head" onClick={() => setOpen(isOpen ? null : a)}>
                <span className="er-asset">{a}</span>
                <span className={`badge dir ${d.cls}`}>{d.label}</span>
                <span className="muted small">{(n.headlines || []).length} headlines</span>
                <span className="spacer" />
                <span className="muted small">{fmtTime(n.timestamp)}</span>
                <span className="news-toggle">{isOpen ? '▾' : '▸'}</span>
              </div>
              {isOpen && (
                <div className="news-detail">
                  <div className="news-rationale">{n.rationale}</div>
                  <ul className="news-headlines">
                    {(n.headlines || []).map((h, i) => <li key={i}>{h}</li>)}
                    {(n.headlines || []).length === 0 && <li className="muted">no headlines stored</li>}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function Dashboard() {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [news, setNews] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchData = async () => {
      try {
        const [sigRes, trRes, newsRes] = await Promise.all([
          api.get('/signals/'),
          api.get('/trades/'),
          api.get('/news/'),
        ]);
        if (!alive) return;
        setSignals(sigRes.data);
        setTrades(trRes.data);
        setNews(newsRes.data);
        setErr(null);
      } catch (e) {
        if (alive) setErr(e.response?.data?.detail || 'Failed to load');
      }
    };
    fetchData();
    const t = setInterval(fetchData, REFRESH_MS);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const loadTrades = useCallback(async () => {
    try {
      const r = await api.get('/trades/');
      setTrades(r.data);
    } catch { /* ignore */ }
  }, []);

  const toggleProtect = async (trade, key) => {
    const cur = trade.overrides || {};
    const isOff = cur[key] && cur[key].enabled === false;
    const next = { ...cur };
    if (isOff) delete next[key];
    else next[key] = { enabled: false };
    try {
      await api.put(`/trades/${trade.id}`, { overrides: next });
      loadTrades();
    } catch (e) {
      setErr(e.response?.data?.detail || 'Override failed (owner only)');
    }
  };

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

      <NewsCard news={news} />

      <section className="card">
        <h2>Paper positions</h2>
        <p className="section-sub">
          Auto-opened when a signal arms. Stop/target are the global defaults; toggle a protection
          off <b>for this trade</b> with the SL/TP chips on open positions (owner only).
        </p>
        <table className="positions">
          <thead>
            <tr>
              <th>Asset</th><th>Side</th><th>Entry</th><th>Stop</th><th>Target</th>
              <th>Exit</th><th>P&L</th><th>Status</th><th>Protect</th>
            </tr>
          </thead>
          <tbody>
            {trades.map((t) => {
              const slOff = t.overrides?.stop_loss?.enabled === false;
              const tpOff = t.overrides?.take_profit?.enabled === false;
              const open = t.status === 'open';
              return (
                <tr key={t.id}>
                  <td>{t.asset}</td>
                  <td className={t.side === 'short' ? 'neg' : 'pos'}>{t.side || '—'}</td>
                  <td>{t.entry_price != null ? t.entry_price.toFixed(2) : '—'}</td>
                  <td>{t.stop_loss != null ? t.stop_loss.toFixed(2) : '—'}</td>
                  <td>{t.take_profit != null ? t.take_profit.toFixed(2) : '—'}</td>
                  <td>{t.exit_price != null ? t.exit_price.toFixed(2) : '—'}</td>
                  <td className={(t.pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{t.pnl != null ? `$${t.pnl.toFixed(2)}` : '—'}</td>
                  <td>
                    {open
                      ? <span className="badge st-armed">open</span>
                      : <span className="badge">{t.close_reason || 'closed'}</span>}
                  </td>
                  <td>
                    {open ? (
                      <span className="protect">
                        <button className={`mini ${slOff ? '' : 'on'}`} onClick={() => toggleProtect(t, 'stop_loss')} title="toggle stop-loss for this trade">SL</button>
                        <button className={`mini ${tpOff ? '' : 'on'}`} onClick={() => toggleProtect(t, 'take_profit')} title="toggle take-profit for this trade">TP</button>
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              );
            })}
            {trades.length === 0 && (
              <tr>
                <td colSpan="9" className="empty">No paper positions yet — opens when a signal arms (pending).</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
