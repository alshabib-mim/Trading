import React, { useState, useEffect } from 'react';
import api from '../api';

export default function Assets() {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState('');
  const [symbol, setSymbol] = useState('');
  const [type, setType] = useState('stock');
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const r = await api.get('/assets/');
      setRows(r.data);
      setError('');
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to load assets');
    }
  };

  useEffect(() => { load(); }, []);

  const add = async (e) => {
    e.preventDefault();
    if (!symbol.trim()) return;
    setBusy(true);
    setError('');
    try {
      await api.post('/assets/', { symbol: symbol.trim().toUpperCase(), asset_type: type, enabled: true });
      setSymbol('');
      load();
    } catch (e2) {
      setError(e2.response?.data?.detail || 'Add failed');
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (row) => {
    try {
      await api.put(`/assets/${row.symbol}`, { enabled: !row.enabled });
      load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Update failed');
    }
  };

  const remove = async (row) => {
    try {
      await api.delete(`/assets/${row.symbol}`);
      load();
    } catch (e) {
      setError(e.response?.data?.detail || 'Delete failed');
    }
  };

  const stocks = rows.filter((r) => r.asset_type === 'stock');
  const crypto = rows.filter((r) => r.asset_type === 'crypto');
  const forex = rows.filter((r) => r.asset_type === 'forex');
  const enabledCount = rows.filter((r) => r.enabled).length;

  return (
    <div className="page">
      <h1>Asset universe</h1>
      <p className="section-sub">
        The tracked symbols, read at runtime — add/remove takes effect on the next scheduler
        tick, no redeploy. Type drives everything: stocks use insider/13F/sentiment, crypto uses
        whale flow; forex/gold is technical-only (technical drives direction). {enabledCount} enabled ·
        {' '}{stocks.length} stocks · {crypto.length} crypto · {forex.length} forex.
      </p>
      {error && <div className="error">{error}</div>}

      <form className="card asset-add" onSubmit={add}>
        <input
          type="text"
          placeholder="Symbol (AAPL · SOL-USD · EUR-USD · XAU-USD)"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
        />
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="stock">stock</option>
          <option value="crypto">crypto</option>
          <option value="forex">forex</option>
        </select>
        <button type="submit" disabled={busy}>{busy ? 'Adding…' : 'Add asset'}</button>
      </form>

      <section className="card">
        <table className="positions">
          <thead>
            <tr><th>Symbol</th><th>Type</th><th>Status</th><th>Actions</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.symbol}>
                <td><b>{r.symbol}</b></td>
                <td><span className={`badge ${r.asset_type === 'crypto' ? 'dir-bull' : ''}`}>{r.asset_type}</span></td>
                <td>
                  <span className={`badge ${r.enabled ? 'st-armed' : 'st-watch'}`}>{r.enabled ? 'enabled' : 'disabled'}</span>
                </td>
                <td>
                  <span className="protect">
                    <button className={`mini ${r.enabled ? 'on' : ''}`} onClick={() => toggle(r)}>
                      {r.enabled ? 'disable' : 'enable'}
                    </button>
                    <button className="mini" onClick={() => remove(r)}>remove</button>
                  </span>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan="4" className="empty">No assets — add one above.</td></tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
