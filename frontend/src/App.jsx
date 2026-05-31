import React, { useState, useEffect } from 'react';
import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const Dashboard = () => {
  const [signals, setSignals] = useState([]);
  const [trades, setTrades] = useState([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const signalsRes = await axios.get(`${API_URL}/signals/`);
        setSignals(signalsRes.data);
        const tradesRes = await axios.get(`${API_URL}/trades/`);
        setTrades(tradesRes.data);
      } catch (err) {
        console.error("Error fetching data", err);
      }
    };
    fetchData();
  }, []);

  return (
    <div className="p-8 font-sans">
      <h1 className="text-3xl font-bold mb-6">AI Trading System Dashboard</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <section className="bg-gray-100 p-6 rounded-lg">
          <h2 className="text-xl font-semibold mb-4">Trading Signals</h2>
          <table className="w-full text-left">
            <thead>
              <tr>
                <th className="pb-2">Asset</th>
                <th className="pb-2">Type</th>
                <th className="pb-2">Confidence</th>
                <th className="pb-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {signals.map(s => (
                <tr key={s.id} className="border-t border-gray-300">
                  <td className="py-2">{s.asset}</td>
                  <td className="py-2">{s.signal_type}</td>
                  <td className="py-2">{(s.confidence_score * 100).toFixed(1)}%</td>
                  <td className="py-2">{s.status}</td>
                </tr>
              ))}
              {signals.length === 0 && <tr><td colSpan="4" className="py-4 text-center text-gray-500">No signals found</td></tr>}
            </tbody>
          </table>
        </section>

        <section className="bg-gray-100 p-6 rounded-lg">
          <h2 className="text-xl font-semibold mb-4">Executed Trades</h2>
          <table className="w-full text-left">
            <thead>
              <tr>
                <th className="pb-2">Asset</th>
                <th className="pb-2">Entry</th>
                <th className="pb-2">Size</th>
                <th className="pb-2">PnL</th>
              </tr>
            </thead>
            <tbody>
              {trades.map(t => (
                <tr key={t.id} className="border-t border-gray-300">
                  <td className="py-2">{t.asset}</td>
                  <td className="py-2">${t.entry_price.toFixed(2)}</td>
                  <td className="py-2">{t.size}</td>
                  <td className="py-2 text-green-600">${t.pnl?.toFixed(2) || '0.00'}</td>
                </tr>
              ))}
              {trades.length === 0 && <tr><td colSpan="4" className="py-4 text-center text-gray-500">No trades found</td></tr>}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
};

export default Dashboard;
