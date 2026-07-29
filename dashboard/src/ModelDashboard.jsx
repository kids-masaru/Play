import React, { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const SOURCES = [
  { key: 'stakes', label: '通常予測', color: '#6366f1' },
  { key: 'stakes_det', label: 'Det', color: '#60a5fa' },
  { key: 'stakes_gemini', label: 'Gemini', color: '#10b981' },
  { key: 'stakes_grok', label: 'Grok', color: '#a78bfa' },
  { key: 'stakes_gemmaft', label: '学Gemini', color: '#ec4899' },
  { key: 'stakes_gemmaclaude', label: '学Claude', color: '#06b6d4' },
  { key: 'stakes_gemmagrokx', label: '学Grok+X', color: '#f97316' },
];

const parseStakes = (value) => {
  if (!value) return [];
  const text = String(value);
  try {
    const obj = JSON.parse(text);
    return Object.entries(obj).map(([combo, stake]) => ({ combo: combo.replace(/(\d)(\d)(\d)/, '$1-$2-$3'), stake: Number(stake) || 0 }));
  } catch (_) {
    return [...text.matchAll(/(\d-\d-\d)\s*:\s*(\d+)/g)].map(m => ({ combo: m[1], stake: Number(m[2]) }));
  }
};

const parseCsv = (text) => {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const keys = header.split(',');
  return lines.map(line => Object.fromEntries(keys.map((key, i) => [key, line.split(',')[i] || ''])));
};

const ModelDashboard = () => {
  const [sourceKey, setSourceKey] = useState('stakes');
  const [summary, setSummary] = useState({});
  const [results, setResults] = useState([]);
  const [error, setError] = useState('');
  const [recentOpen, setRecentOpen] = useState(false);

  useEffect(() => {
    const cb = `?t=${Date.now()}`;
    Promise.all([
      fetch(`./daily_data/ai_predictions_summary.json${cb}`).then(r => r.ok ? r.json() : {}),
      fetch(`./daily_data/daily_history_results.csv${cb}`).then(r => r.ok ? r.text() : ''),
    ]).then(([s, csv]) => { setSummary(s); setResults(csv ? parseCsv(csv) : []); })
      .catch(() => setError('成績データを読み込めませんでした。'));
  }, []);

  const source = SOURCES.find(s => s.key === sourceKey) || SOURCES[0];
  const races = useMemo(() => results.map(r => {
    const rid = String(r.ID || r.RaceID || '');
    const picks = parseStakes(summary[rid]?.[sourceKey]);
    const result = String(r.Result || '').replace(/\s/g, '');
    const payout = Number(r.Payout) || 0;
    const hitPick = picks.find(p => p.combo === result);
    const invest = picks.reduce((n, p) => n + p.stake, 0);
    const ret = hitPick ? hitPick.stake * payout / 100 : 0;
    return { id: rid, date: r.Date || '', venue: r.Venue || '', r: r.R || '', result, picks, invest, ret, hit: !!hitPick };
  }).filter(r => r.picks.length > 0), [results, summary, sourceKey]);

  const stats = useMemo(() => {
    const invest = races.reduce((n, r) => n + r.invest, 0);
    const ret = races.reduce((n, r) => n + r.ret, 0);
    return { n: races.length, hits: races.filter(r => r.hit).length, invest, ret, roi: invest ? ret / invest * 100 : 0 };
  }, [races]);
  const trend = useMemo(() => {
    const byDate = {};
    races.forEach(r => { const d = byDate[r.date] || (byDate[r.date] = { date: r.date, invest: 0, ret: 0 }); d.invest += r.invest; d.ret += r.ret; });
    let invest = 0, ret = 0;
    return Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date)).map(d => { invest += d.invest; ret += d.ret; return { date: d.date.slice(5), roi: invest ? Math.round(ret / invest * 1000) / 10 : 0 }; });
  }, [races]);
  const venue = useMemo(() => Object.values(races.reduce((m, r) => { const v = m[r.venue] || (m[r.venue] = { venue: r.venue, n: 0, hits: 0 }); v.n++; if (r.hit) v.hits++; return m; }, {})).map(v => ({ ...v, hitRate: Math.round(v.hits / v.n * 1000) / 10 })).sort((a, b) => b.hitRate - a.hitRate), [races]);

  return <div>
    <div className="tab-container" style={{ marginBottom: '1rem', flexWrap: 'wrap' }}>
      {SOURCES.map(s => <button key={s.key} className={`tab-button ${s.key === sourceKey ? 'active' : ''}`} onClick={() => setSourceKey(s.key)}>{s.label}</button>)}
    </div>
    <div style={{ marginBottom: '1rem', fontSize: '0.85rem', color: source.color, fontWeight: 700 }}>{source.label} の成績ダッシュボード（結果確定済み {stats.n} レース）</div>
    {error && <div className="glass-card" style={{ padding: '1rem' }}>{error}</div>}
    <div className="stats-grid">
      {[['ROI', `${stats.roi.toFixed(1)}%`], ['Hit Rate', stats.n ? `${(stats.hits / stats.n * 100).toFixed(1)}%` : '-'], ['Invest', `¥${stats.invest.toLocaleString()}`], ['Return', `¥${stats.ret.toLocaleString()}`]].map(([label, value]) => <div className="glass-card stat-item" key={label}><span className="stat-label">{label}</span><span className="stat-value">{value}</span></div>)}
    </div>
    <div className="charts-grid">
      <div className="glass-card chart-container full-width-chart"><h3>ROI推移</h3><ResponsiveContainer width="100%" height="85%"><AreaChart data={trend}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="date" /><YAxis unit="%" /><Tooltip /><Area dataKey="roi" stroke={source.color} fill={source.color} fillOpacity={0.18} /></AreaChart></ResponsiveContainer></div>
      <div className="glass-card chart-container"><h3>会場別的中率</h3><ResponsiveContainer width="100%" height="85%"><BarChart data={venue}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="venue" /><YAxis unit="%" /><Tooltip /><Bar dataKey="hitRate" fill={source.color} /></BarChart></ResponsiveContainer></div>
    </div>
    <div className="prediction-list">
      <button className="toggle-reasoning" onClick={() => setRecentOpen(open => !open)}>
        {recentOpen ? '▼ 直近の確定レースを閉じる' : '▶ 直近の確定レースを表示'}
      </button>
      {recentOpen && [...races].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 20).map(r => <div key={r.id} className={r.hit ? 'race-card hit' : 'race-card miss'}><strong>{r.date} {r.venue} {r.r}R</strong><span>{r.hit ? 'HIT' : 'MISS'} / {r.result}</span><span>{r.picks.map(p => p.combo).join(', ')}</span><span>収支 ¥{Math.round(r.ret - r.invest).toLocaleString()}</span></div>)}
    </div>
  </div>;
};

export default ModelDashboard;
