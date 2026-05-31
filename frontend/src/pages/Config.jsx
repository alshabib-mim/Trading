import React, { useState, useEffect } from 'react';
import api from '../api';

function SourceCard({ row, onSaved }) {
  const [provider, setProvider] = useState(row.provider || '');
  const [enabled, setEnabled] = useState(!!row.enabled);
  const [weight, setWeight] = useState(row.weight ?? '');
  const [freshness, setFreshness] = useState(row.freshness_seconds ?? '');
  const [interval, setInterval] = useState(row.interval_seconds ?? '');
  const [optionsText, setOptionsText] = useState(
    row.options ? JSON.stringify(row.options, null, 2) : ''
  );
  const [credential, setCredential] = useState('');
  const [clearCredential, setClearCredential] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const save = async () => {
    setMsg(null);

    let options;
    if (optionsText.trim()) {
      try {
        options = JSON.parse(optionsText);
      } catch {
        setMsg({ kind: 'error', text: 'Options is not valid JSON' });
        return;
      }
    } else {
      options = {};
    }

    const payload = {
      provider,
      enabled,
      weight: weight === '' ? null : Number(weight),
      freshness_seconds: freshness === '' ? null : Number(freshness),
      interval_seconds: interval === '' ? null : Number(interval),
      options,
      clear_credential: clearCredential,
    };
    if (!clearCredential && credential) {
      payload.credential = credential;
    }

    setBusy(true);
    try {
      const res = await api.put(`/config/sources/${row.source}`, payload);
      setCredential('');
      setClearCredential(false);
      setMsg({ kind: 'ok', text: 'Saved' });
      if (onSaved) onSaved(res.data);
    } catch (err) {
      setMsg({ kind: 'error', text: err.response?.data?.detail || 'Save failed' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card source-card">
      <div className="source-head">
        <h2>{row.source}</h2>
        <span className={`badge ${row.has_credential ? 'badge-set' : 'badge-none'}`}>
          {row.has_credential ? 'key set ••••' : 'no key'}
        </span>
      </div>

      <label>
        Provider
        <input value={provider} onChange={(e) => setProvider(e.target.value)} />
      </label>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        Enabled
      </label>

      <div className="row3">
        <label>
          Weight
          <input
            type="number"
            step="0.1"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
          />
        </label>
        <label>
          Freshness (s)
          <input
            type="number"
            value={freshness}
            onChange={(e) => setFreshness(e.target.value)}
          />
        </label>
        <label>
          Interval (s)
          <input
            type="number"
            value={interval}
            onChange={(e) => setInterval(e.target.value)}
          />
        </label>
      </div>

      <label>
        Options (JSON)
        <textarea
          rows="4"
          value={optionsText}
          onChange={(e) => setOptionsText(e.target.value)}
        />
      </label>

      <label>
        {row.has_credential ? 'Replace API key / token' : 'API key / token'}
        <input
          type="password"
          value={credential}
          placeholder={row.has_credential ? 'leave blank to keep current' : ''}
          disabled={clearCredential}
          onChange={(e) => setCredential(e.target.value)}
        />
      </label>

      {row.has_credential && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={clearCredential}
            onChange={(e) => setClearCredential(e.target.checked)}
          />
          Clear stored key
        </label>
      )}

      <div className="source-foot">
        <button onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        {msg && <span className={msg.kind === 'ok' ? 'ok' : 'error'}>{msg.text}</span>}
      </div>
    </section>
  );
}

export default function Config() {
  const [sources, setSources] = useState([]);
  const [error, setError] = useState('');

  const load = async () => {
    setError('');
    try {
      const res = await api.get('/config/sources');
      setSources(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load sources');
    }
  };

  useEffect(() => {
    load();
  }, []);

  const onSaved = (updated) => {
    setSources((prev) =>
      prev.map((s) => (s.source === updated.source ? updated : s))
    );
  };

  return (
    <div className="page">
      <h1>Source Configuration</h1>
      {error && <div className="error">{error}</div>}
      <div className="grid">
        {sources.map((row) => (
          <SourceCard key={row.source} row={row} onSaved={onSaved} />
        ))}
      </div>
    </div>
  );
}
