import React, { useState, useEffect } from 'react';
import api from '../api';

export default function Dashboard() {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const signalsRes = await api.get('/signals/');
        setSignals(signalsRes.data);
        const tradesRes = await api.get('/trades/');
        setTrades(tradesRes.data);
      } catch (err) {
        console.error('Error fetching data', err);
      }
    };
    fetchData();
  }, []);

  return (
    <div className="page">
      <h1>AI Trading System Dashboard</h1>

      <div className="grid">
        <section className="card">
          <h2>Trading Signals</h2>
          <table>
            <thead>
              <tr>
                <th>Asset</th>
                <th>Type</th>
                <th>Confidence</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.id}>
                  <td>{s.asset}</td>
                  <td>{s.signal_type}</td>
                  <td>{(s.confidence_score * 100).toFixed(1)}%</td>
                  <td>{s.status}</td>
                </tr>
              ))}
              {signals.length === 0 && (
                <tr>
                  <td colSpan="4" className="empty">No signals found</td>
                </tr>
              )}
            </tbody>
          </table>
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
                  <td colSpan="4" className="empty">No trades found</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
