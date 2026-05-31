import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';
import { setToken } from '../auth';

export default function Login({ onAuthed }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const body = new URLSearchParams();
      body.append('username', username);
      body.append('password', password);
      const res = await api.post('/auth/token', body, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      setToken(res.data.access_token);
      if (onAuthed) await onAuthed();
      navigate('/');
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <form className="card auth-card" onSubmit={submit}>
        <h1>Sign in</h1>
        {error && <div className="error">{error}</div>}
        <label>
          Username
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
