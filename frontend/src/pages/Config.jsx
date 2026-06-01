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

const EVENT_LABELS = {
  signal_armed: 'Signal arms (watch → pending)',
  position_opened: 'Paper position opens',
  exit_hit: 'Stop / take-profit hits',
  breaker: 'Circuit breaker fires',
};

function AlertsCard() {
  const [cfg, setCfg] = useState(null);
  const [enabled, setEnabled] = useState(false);
  const [events, setEvents] = useState({});
  const [botToken, setBotToken] = useState('');
  const [chatId, setChatId] = useState('');
  const [clearToken, setClearToken] = useState(false);
  const [clearChat, setClearChat] = useState(false);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState(null);

  const load = async () => {
    try {
      const { data } = await api.get('/alerts/');
      setCfg(data);
      setEnabled(data.enabled);
      setEvents(data.events || {});
    } catch (e) {
      setMsg({ kind: 'error', text: e.response?.data?.detail || 'Failed to load alerts' });
    }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    setBusy(true); setMsg(null);
    const payload = { enabled, events, clear_bot_token: clearToken, clear_chat_id: clearChat };
    if (!clearToken && botToken) payload.bot_token = botToken;
    if (!clearChat && chatId) payload.chat_id = chatId;
    try {
      const { data } = await api.put('/alerts/', payload);
      setCfg(data); setEnabled(data.enabled); setEvents(data.events || {});
      setBotToken(''); setChatId(''); setClearToken(false); setClearChat(false);
      setMsg({ kind: 'ok', text: 'Saved' });
    } catch (e) {
      setMsg({ kind: 'error', text: e.response?.data?.detail || 'Save failed' });
    } finally { setBusy(false); }
  };

  const sendTest = async () => {
    setTesting(true); setMsg(null);
    try {
      await api.post('/alerts/test');
      setMsg({ kind: 'ok', text: 'Test alert sent — check Telegram' });
    } catch (e) {
      setMsg({ kind: 'error', text: e.response?.data?.detail || 'Test failed' });
    } finally { setTesting(false); }
  };

  if (!cfg) return null;

  return (
    <section className="card source-card alerts-card">
      <div className="source-head">
        <h2>Alerts — Telegram</h2>
        <span className={`badge ${cfg.has_bot_token && cfg.has_chat_id ? 'badge-set' : 'badge-none'}`}>
          {cfg.has_bot_token && cfg.has_chat_id ? 'creds set ••••' : 'creds missing'}
        </span>
      </div>
      <p className="section-sub">
        Free, no per-message cost. Get a bot token from <b>@BotFather</b> and your numeric chat id
        (e.g. from <b>@userinfobot</b>), paste them below (encrypted at rest), then send a test.
      </p>

      <label className="checkbox">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        Enabled (master switch)
      </label>

      <div className="alerts-events">
        {(cfg.event_types || []).map((k) => (
          <label key={k} className="checkbox">
            <input
              type="checkbox"
              checked={events[k] !== false}
              onChange={(e) => setEvents({ ...events, [k]: e.target.checked })}
            />
            {EVENT_LABELS[k] || k}
          </label>
        ))}
      </div>

      <label>
        {cfg.has_bot_token ? 'Replace bot token' : 'Bot token (from @BotFather)'}
        <input
          type="password" value={botToken}
          placeholder={cfg.has_bot_token ? 'leave blank to keep current' : '123456:ABC-...'}
          disabled={clearToken}
          onChange={(e) => setBotToken(e.target.value)}
        />
      </label>
      {cfg.has_bot_token && (
        <label className="checkbox">
          <input type="checkbox" checked={clearToken} onChange={(e) => setClearToken(e.target.checked)} />
          Clear stored token
        </label>
      )}

      <label>
        {cfg.has_chat_id ? 'Replace chat id' : 'Chat id'}
        <input
          type="password" value={chatId}
          placeholder={cfg.has_chat_id ? 'leave blank to keep current' : 'e.g. 123456789'}
          disabled={clearChat}
          onChange={(e) => setChatId(e.target.value)}
        />
      </label>
      {cfg.has_chat_id && (
        <label className="checkbox">
          <input type="checkbox" checked={clearChat} onChange={(e) => setClearChat(e.target.checked)} />
          Clear stored chat id
        </label>
      )}

      <div className="source-foot">
        <button onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
        <button onClick={sendTest} disabled={testing || !(cfg.has_bot_token && cfg.has_chat_id)}>
          {testing ? 'Sending…' : 'Send test'}
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
      <AlertsCard />
      <div className="grid">
        {sources.map((row) => (
          <SourceCard key={row.source} row={row} onSaved={onSaved} />
        ))}
      </div>
    </div>
  );
}
