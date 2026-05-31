import React, { useState, useEffect } from 'react';
import AssetChart from '../components/AssetChart';
import api from '../api';

// Render order + display labels for the asset-type groups (matches the dashboard).
const TYPE_ORDER = { stock: 0, crypto: 1, forex: 2 };
const TYPE_LABEL = { stock: 'Stocks', crypto: 'Crypto', forex: 'Forex / Gold' };

function typeOf(sig) {
  if (sig && sig.asset_type) return sig.asset_type;
  return sig && sig.asset && sig.asset.includes('-') ? 'crypto' : 'stock';
}

export default function Charts() {
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        // Same source of truth as the dashboard: the signals feed carries every
        // enabled asset (a fusion row per asset each cycle) plus its asset_type.
        const { data } = await api.get('/signals/');
        if (!alive) return;
        const latest = {};
        for (const s of data) if (!(s.asset in latest)) latest[s.asset] = s;
        const list = Object.values(latest).sort((a, b) => {
          const ta = TYPE_ORDER[typeOf(a)] ?? 9;
          const tb = TYPE_ORDER[typeOf(b)] ?? 9;
          return ta - tb || a.asset.localeCompare(b.asset);
        });
        setRows(list);
        setErr(null);
      } catch (e) {
        if (alive) setErr(e.response?.data?.detail || 'Failed to load asset list');
      }
    })();
    return () => { alive = false; };
  }, []);

  // Group rows by type for sub-headed rendering.
  const groups = [];
  let curType = null;
  for (const s of rows) {
    const t = typeOf(s);
    if (t !== curType) { groups.push({ type: t, rows: [] }); curType = t; }
    groups[groups.length - 1].rows.push(s);
  }

  return (
    <div className="page charts-page">
      <h1>Technical Analysis — what the system sees</h1>
      <p className="charts-sub">
        1h candles · ~30d history · RSI 14 / MACD 12-26-9 / SMA 20-50 / Donchian 20 /
        Fibonacci · live (60s refresh). The exact OHLCV + pandas-ta the engine reads.
        Stocks via yfinance, crypto via the exchange feed, forex/gold via Twelve Data.
      </p>
      {err && <div className="error">{err}</div>}
      {rows.length === 0 && !err && <p className="charts-sub muted">Loading assets…</p>}
      {groups.map((g) => (
        <section key={g.type} className="charts-group">
          <h2 className="group-head">{TYPE_LABEL[g.type] || g.type} <span className="muted small">({g.rows.length})</span></h2>
          <div className="charts-grid">
            {g.rows.map((s) => (
              <AssetChart key={s.asset} asset={s.asset} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
