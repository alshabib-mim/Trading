import React, { useState, useEffect, useCallback } from 'react';
import {
  HashRouter,
  Routes,
  Route,
  Navigate,
  Link,
  useNavigate,
} from 'react-router-dom';
import api from './api';
import { isAuthed, clearToken } from './auth';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Config from './pages/Config';
import './config.css';

function Shell({ children, me, onLogout }) {
  return (
    <div className="shell">
      <nav className="nav">
        <span className="brand">Trading</span>
        <Link to="/">Dashboard</Link>
        {me?.role === 'owner' && <Link to="/config">Config</Link>}
        <span className="spacer" />
        {me && <span className="who">{me.username}</span>}
        <button className="link-btn" onClick={onLogout}>Logout</button>
      </nav>
      <main>{children}</main>
    </div>
  );
}

function Protected({ children }) {
  if (!isAuthed()) return <Navigate to="/login" replace />;
  return children;
}

function OwnerOnly({ me, children }) {
  if (!isAuthed()) return <Navigate to="/login" replace />;
  if (me && me.role !== 'owner') return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  const [me, setMe] = useState(null);
  const navigate = useNavigate();

  const refreshMe = useCallback(async () => {
    if (!isAuthed()) {
      setMe(null);
      return;
    }
    try {
      const res = await api.get('/auth/me');
      setMe(res.data);
    } catch {
      setMe(null);
    }
  }, []);

  useEffect(() => {
    refreshMe();
  }, [refreshMe]);

  const logout = () => {
    clearToken();
    setMe(null);
    navigate('/login');
  };

  return (
    <Routes>
      <Route path="/login" element={<Login onAuthed={refreshMe} />} />
      <Route
        path="/"
        element={
          <Protected>
            <Shell me={me} onLogout={logout}>
              <Dashboard />
            </Shell>
          </Protected>
        }
      />
      <Route
        path="/config"
        element={
          <OwnerOnly me={me}>
            <Shell me={me} onLogout={logout}>
              <Config />
            </Shell>
          </OwnerOnly>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <HashRouter>
      <AppRoutes />
    </HashRouter>
  );
}
