import React from 'react';
import AssetChart from '../components/AssetChart';

const ASSETS = ['AAPL', 'TSLA', 'BTC-USD', 'ETH-USD'];

export default function Charts() {
  return (
    <div className="page charts-page">
      <h1>Technical Analysis — what the system sees</h1>
      <p className="charts-sub">
        1h candles · ~30d history · RSI 14 / MACD 12-26-9 / SMA 20-50 / Donchian 20 /
        Fibonacci · live (60s refresh). The exact OHLCV + pandas-ta the engine reads.
      </p>
      <div className="charts-grid">
        {ASSETS.map((a) => (
          <AssetChart key={a} asset={a} />
        ))}
      </div>
    </div>
  );
}
