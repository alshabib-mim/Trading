import React, { useEffect, useRef, useState } from 'react';
import { createChart, CrosshairMode, LineStyle } from 'lightweight-charts';
import api from '../api';

const REFRESH_MS = 60000;

const FIB_COLORS = {
  '0.0%': '#6b7280',
  '23.6%': '#38bdf8',
  '38.2%': '#22c55e',
  '50.0%': '#eab308',
  '61.8%': '#f97316',
  '78.6%': '#ef4444',
  '100.0%': '#a855f7',
};

export default function AssetChart({ asset }) {
  const priceRef = useRef(null);
  const rsiRef = useRef(null);
  const macdRef = useRef(null);
  const objs = useRef({});
  const fibLines = useRef([]);
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const base = {
      layout: { background: { color: '#15181e' }, textColor: '#9aa0a8', fontSize: 11 },
      grid: { vertLines: { color: '#21252d' }, horzLines: { color: '#21252d' } },
      rightPriceScale: { borderColor: '#2c313a' },
      timeScale: { borderColor: '#2c313a', timeVisible: true, secondsVisible: false },
      crosshair: { mode: CrosshairMode.Normal },
    };

    const priceChart = createChart(priceRef.current, { ...base, height: 340 });
    const rsiChart = createChart(rsiRef.current, { ...base, height: 120 });
    const macdChart = createChart(macdRef.current, { ...base, height: 140 });

    const candle = priceChart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444', borderVisible: false,
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });
    const sma20 = priceChart.addLineSeries({ color: '#3b82f6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const sma50 = priceChart.addLineSeries({ color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const dcUpper = priceChart.addLineSeries({ color: '#8b5cf6', lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false });
    const dcMid = priceChart.addLineSeries({ color: '#8b5cf6', lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false });
    const dcLower = priceChart.addLineSeries({ color: '#8b5cf6', lineWidth: 1, lineStyle: LineStyle.Dotted, priceLineVisible: false, lastValueVisible: false });

    const rsi = rsiChart.addLineSeries({ color: '#e6e8eb', lineWidth: 1, priceLineVisible: false, lastValueVisible: true });
    [70, 50, 30].forEach((lvl) => rsi.createPriceLine({
      price: lvl,
      color: lvl === 50 ? '#3a3f48' : lvl === 70 ? '#ef444466' : '#22c55e66',
      lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: String(lvl),
    }));

    const macd = macdChart.addLineSeries({ color: '#3b82f6', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const macdSignal = macdChart.addLineSeries({ color: '#f59e0b', lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
    const macdHist = macdChart.addHistogramSeries({ priceLineVisible: false, lastValueVisible: false });

    objs.current = {
      candle, sma20, sma50, dcUpper, dcMid, dcLower, rsi, macd, macdSignal, macdHist,
    };

    // Sync the three time scales (pan/zoom one → all follow).
    const charts = [priceChart, rsiChart, macdChart];
    let syncing = false;
    charts.forEach((src) => {
      src.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return;
        syncing = true;
        charts.forEach((t) => { if (t !== src) t.timeScale().setVisibleLogicalRange(range); });
        syncing = false;
      });
    });

    const ro = new ResizeObserver(() => {
      const w = priceRef.current ? priceRef.current.clientWidth : 600;
      charts.forEach((c) => c.applyOptions({ width: w }));
    });
    if (priceRef.current) ro.observe(priceRef.current);

    let alive = true;
    let timer = null;

    async function load(first) {
      try {
        const { data } = await api.get(`/charts/${asset}`);
        if (!alive) return;
        const o = objs.current;
        const ind = data.indicators;
        o.candle.setData(data.candles);
        o.sma20.setData(ind.sma20);
        o.sma50.setData(ind.sma50);
        o.dcUpper.setData(ind.donchian_upper);
        o.dcMid.setData(ind.donchian_mid);
        o.dcLower.setData(ind.donchian_lower);
        o.rsi.setData(ind.rsi);
        o.macd.setData(ind.macd);
        o.macdSignal.setData(ind.macd_signal);
        o.macdHist.setData(ind.macd_hist.map((p) => ({
          time: p.time, value: p.value,
          color: p.value >= 0 ? '#22c55e88' : '#ef444488',
        })));

        fibLines.current.forEach((pl) => o.candle.removePriceLine(pl));
        fibLines.current = data.fib.levels.map((l) => o.candle.createPriceLine({
          price: l.price, color: FIB_COLORS[l.label] || '#6b7280', lineWidth: 1,
          lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: `fib ${l.label}`,
        }));

        const lastRsi = ind.rsi.length ? ind.rsi[ind.rsi.length - 1].value : null;
        const lastMacd = ind.macd.length ? ind.macd[ind.macd.length - 1].value : null;
        const lastHist = ind.macd_hist.length ? ind.macd_hist[ind.macd_hist.length - 1].value : null;
        setStats({ close: data.last_close, rsi: lastRsi, macd: lastMacd, hist: lastHist, exch: data.exchange, n: data.candles.length });
        setError(null);
        if (first) charts.forEach((c) => c.timeScale().fitContent());
      } catch (e) {
        if (alive) setError(e.response?.data?.detail || 'Failed to load chart data');
      }
    }

    load(true);
    timer = setInterval(() => load(false), REFRESH_MS);

    return () => {
      alive = false;
      if (timer) clearInterval(timer);
      ro.disconnect();
      priceChart.remove();
      rsiChart.remove();
      macdChart.remove();
    };
  }, [asset]);

  const cls = (v, hot, cold) => (v == null ? '' : v >= hot ? 'hot' : v <= cold ? 'cold' : '');

  return (
    <div className="chart-card">
      <div className="chart-head">
        <h3>{asset}</h3>
        {stats && (
          <div className="chart-stats">
            <span className="px">{stats.close}</span>
            <span>RSI <b className={cls(stats.rsi, 70, 30)}>{stats.rsi != null ? stats.rsi.toFixed(1) : '—'}</b></span>
            <span>MACD <b className={stats.macd >= 0 ? 'pos' : 'neg'}>{stats.macd != null ? stats.macd.toFixed(2) : '—'}</b></span>
            <span className="muted">{stats.exch} · {stats.n}×1h</span>
          </div>
        )}
        {error && <span className="error">{error}</span>}
      </div>
      <div className="pane" ref={priceRef} />
      <div className="pane-label">RSI 14</div>
      <div className="pane" ref={rsiRef} />
      <div className="pane-label">MACD 12 / 26 / 9</div>
      <div className="pane" ref={macdRef} />
      <div className="chart-legend">
        <span><i style={{ background: '#3b82f6' }} />SMA20</span>
        <span><i style={{ background: '#f59e0b' }} />SMA50</span>
        <span><i style={{ background: '#8b5cf6' }} />Donchian 20</span>
        <span><i style={{ background: '#a855f7' }} />Fibonacci</span>
      </div>
    </div>
  );
}
