import React, { useState, useEffect, useCallback } from 'react';
import api from '../api';

const ARM_THRESHOLD = 0.6;
const REFRESH_MS = 30000;

// Render order + display labels for the asset-type groups.
const TYPE_ORDER = { stock: 0, crypto: 1, forex: 2 };
const TYPE_LABEL = { stock: 'Stocks', crypto: 'Crypto', forex: 'Forex / Gold' };

// Confirmation flags shown per row. news_conf is forex-only (null elsewhere → unlit).
const FLAGS = [
  { key: 'whale_conf', label: 'Whale' },
  { key: 'technical_conf', label: 'Tech' },
  { key: 'sentiment_conf', label: 'Sent' },
  { key: 'institutional_conf', label: '13F' },
  { key: 'news_conf', label: 'News' },
];

function typeOf(sig) {
  // Fall back to a symbol heuristic only if the API didn't supply a type.
  if (sig && sig.asset_type) return sig.asset_type;
  return sig && sig.asset && sig.asset.includes('-') ? 'crypto' : 'stock';
}

// Which source sets DIRECTION for this asset type (what the dashboard labels).
function dirSource(type) {
  if (type === 'crypto') return 'whale flow';
  if (type === 'forex') return 'technical';
  return 'insider (Form 4)';
}
function convLabel(type) {
  if (type === 'crypto') return 'whale';
  if (type === 'forex') return 'technical';
  return 'insider';
}

function dirClass(d) {
  return d === 'bullish' ? 'dir-bull' : d === 'bearish' ? 'dir-bear' : 'dir-none';
}

// The API sends naive UTC timestamps (no 'Z'/offset), which the browser would
// otherwise parse as LOCAL time. Force UTC parsing so everything renders in the
// viewer's local zone (with a zone label), consistent across the dashboard.
function parseUTC(ts) {
  if (ts == null) return null;
  let s = String(ts);
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) s += 'Z';
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

function fmtTime(ts) {
  const d = parseUTC(ts);
  return d ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' }) : '';
}

// "3 min ago" / "in 12 min" / "just now", relative to the viewer's clock.
function relTime(ts) {
  const d = parseUTC(ts);
  if (!d) return null;
  const diff = d.getTime() - Date.now();
  if (Math.abs(diff) < 45000) return 'just now';
  const mins = Math.round(Math.abs(diff) / 60000);
  const mag = mins < 60 ? `${mins} min` : mins < 60 * 48 ? `${Math.round(mins / 60)} h` : `${Math.round(mins / 1440)} d`;
  return diff < 0 ? `${mag} ago` : `in ${mag}`;
}

function StatusPanel({ status }) {
  if (!status) return null;
  const mk = status.markets || {};
  return (
    <section className="card status-card">
      <div className="status-markets">
        <span className="status-hd">Markets</span>
        {['stock', 'crypto', 'forex'].map((k) => mk[k] && (
          <span key={k} className={`mkt ${mk[k].open ? 'open' : 'closed'}`} title={mk[k].detail}>
            {mk[k].label}: {mk[k].open ? 'OPEN' : 'CLOSED'}
          </span>
        ))}
      </div>
      <div className="status-sources">
        <span className="status-hd">Data sources</span>
        {(status.sources || []).map((s) => {
          const upd = parseUTC(s.last_updated);
          return (
            <div key={s.key} className={`status-src ${s.enabled ? '' : 'off'}`}>
              <span className="ss-label">{s.label}</span>
              <span className="ss-cadence">{s.cadence}</span>
              <span className="ss-updated" title={upd ? upd.toLocaleString([], { timeZoneName: 'short' }) : ''}>
                {s.last_updated ? `updated ${relTime(s.last_updated)}` : 'no data yet'}
              </span>
              <span className="ss-next">
                {s.enabled ? (s.next_run ? `next ${relTime(s.next_run)}` : '—') : 'disabled'}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function EngineRow({ sig }) {
  const type = typeOf(sig);
  const conf = (sig.confidence_score || 0) * 100;
  const armed = sig.status === 'pending';
  return (
    <div className={`engine-row ${armed ? 'armed' : ''}`}>
      <div className="er-head">
        <span className="er-asset">{sig.asset}</span>
        <span className={`badge dir ${dirClass(sig.direction)}`}>{sig.direction || 'none'}</span>
        <span className={`badge status ${armed ? 'st-armed' : 'st-watch'}`}>{sig.status}</span>
        <span className="spacer" />
        <span className="muted small">dir: {dirSource(type)}</span>
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
            {convLabel(type)} {sig.direction_conviction.toFixed(2)}
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

function NewsCard({ stocks, news }) {
  const [open, setOpen] = useState(null);
  const byAsset = {};
  for (const n of news) byAsset[n.asset] = n;

  return (
    <section className="card">
      <h2>News &amp; sentiment</h2>
      <p className="section-sub">
        What the sentiment AI read. Finnhub headlines + Claude’s rationale per stock.
        Sentiment is confirm-only — it nudges confidence, never sets direction. Crypto uses
        whale flow; forex uses its own macro-news source (not shown here).
      </p>
      <div className="engine-list">
        {stocks.map((a) => {
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
        {stocks.length === 0 && (
          <div className="engine-row"><div className="er-head"><span className="muted small">no stocks enabled</span></div></div>
        )}
      </div>
    </section>
  );
}

export default function Dashboard() {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);
  const [news, setNews] = useState([]);
  const [status, setStatus] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    const fetchData = async () => {
      try {
        const [sigRes, trRes, newsRes, statusRes] = await Promise.all([
          api.get('/signals/'),
          api.get('/trades/'),
          api.get('/news/'),
          api.get('/status/'),
        ]);
        if (!alive) return;
        setSignals(sigRes.data);
        setTrades(trRes.data);
        setNews(newsRes.data);
        setStatus(statusRes.data);
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

  // Latest signal per asset (list is newest-first → first hit wins). This is the
  // source of truth for what's live — every enabled asset gets a fusion row each
  // cycle, so the dashboard now shows them ALL, grouped by type.
  const latest = {};
  for (const s of signals) {
    if (!(s.asset in latest)) latest[s.asset] = s;
  }
  const rows = Object.values(latest).sort((a, b) => {
    const ta = TYPE_ORDER[typeOf(a)] ?? 9;
    const tb = TYPE_ORDER[typeOf(b)] ?? 9;
    return ta - tb || a.asset.localeCompare(b.asset);
  });
  const stocks = rows.filter((s) => typeOf(s) === 'stock').map((s) => s.asset);

  // Group rows by type for sub-headed rendering.
  const groups = [];
  let curType = null;
  for (const s of rows) {
    const t = typeOf(s);
    if (t !== curType) { groups.push({ type: t, rows: [] }); curType = t; }
    groups[groups.length - 1].rows.push(s);
  }

  return (
    <div className="page">
      <h1>AI Trading System Dashboard</h1>
      {err && <div className="error">{err}</div>}

      <StatusPanel status={status} />

      <section className="card">
        <h2>Engine read — current <span className="muted small">({rows.length} assets)</span></h2>
        <p className="section-sub">
          A signal <b>arms</b> (pending) only when there is a direction, technical timing
          agrees, and confidence ≥ {ARM_THRESHOLD * 100}%. Otherwise it’s a <b>watch</b> row —
          the engine sees something but the sources haven’t lined up. Lit flags = sources
          that agreed with the read direction. Direction source: stocks = insider, crypto =
          whale flow, forex/gold = technical.
        </p>
        {rows.length === 0 && <div className="engine-row"><div className="er-head"><span className="muted">no signals yet — the engine hasn’t run a fusion cycle</span></div></div>}
        {groups.map((g) => (
          <div key={g.type} className="engine-group">
            <h3 className="group-head">{TYPE_LABEL[g.type] || g.type} <span className="muted small">({g.rows.length})</span></h3>
            <div className="engine-list">
              {g.rows.map((s) => <EngineRow key={s.asset} sig={s} />)}
            </div>
          </div>
        ))}
      </section>

      <NewsCard stocks={stocks} news={news} />

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
