import React, { useEffect, useMemo, useState } from 'react';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity, CircleDollarSign, Database, Sparkles, Target, TrendingUp } from 'lucide-react';

const SOURCES = [
  { key: 'stakes', label: '通常予測', short: '通常', color: '#6366f1', description: 'gemma4:e2b と計算モデルの通常運用' },
  { key: 'stakes_det', label: 'Det（計算）', short: 'Det', color: '#2563eb', description: '過去実績を特徴量にした LightGBM 予測' },
  { key: 'stakes_gemini', label: 'Gemini', short: 'Gemini', color: '#059669', description: 'Gemini が出走表と直前情報から判断' },
  { key: 'stakes_grok', label: 'Grok', short: 'Grok', color: '#7c3aed', description: 'Grok がレース情報を読んで予測' },
  { key: 'stakes_gemmaft', label: '学習Gemma（Gemini先生）', short: '学Gemini', color: '#db2777', description: 'Gemini教師データで学習した Gemma' },
  { key: 'stakes_gemmaclaude', label: '学習Gemma（Claude先生）', short: '学Claude', color: '#0891b2', description: 'Claude教師データで学習した Gemma' },
  { key: 'stakes_gemmagrokx', label: '学習Gemma（Grok+X先生）', short: '学Grok+X', color: '#ea580c', description: 'GrokとX情報を教師に学習した Gemma' },
  { key: 'stakes_codex', label: 'Codex', short: 'Codex', color: '#0d9488', description: '過去の結果から自動フィードバックする Codex' },
];

const parseStakes = (value) => {
  if (!value) return [];
  const text = String(value);
  try {
    const obj = JSON.parse(text);
    return Object.entries(obj).map(([combo, stake]) => ({ combo: combo.replace(/(\d)(\d)(\d)/, '$1-$2-$3'), stake: Number(stake) || 0 }));
  } catch {
    return [...text.matchAll(/(\d-\d-\d)\s*:\s*(\d+)/g)].map(m => ({ combo: m[1], stake: Number(m[2]) }));
  }
};

const parseCsv = (text) => {
  const [header, ...lines] = text.trim().split(/\r?\n/);
  const keys = header.split(',');
  return lines.map(line => Object.fromEntries(keys.map((key, i) => [key, line.split(',')[i] || ''])));
};

const PERIOD_LABEL = { weekly: '直近7日', monthly: '直近30日', total: '全期間' };

const ModelDashboard = ({ period = 'total' }) => {
  const [sourceKey, setSourceKey] = useState('stakes');
  const [summary, setSummary] = useState({});
  const [results, setResults] = useState([]);
  const [codexLearning, setCodexLearning] = useState(null);
  const [error, setError] = useState('');
  const [recentOpen, setRecentOpen] = useState(false);

  useEffect(() => {
    const cb = `?t=${Date.now()}`;
    Promise.all([
      fetch(`./daily_data/ai_predictions_summary.json${cb}`).then(r => r.ok ? r.json() : {}),
      fetch(`./daily_data/daily_history_results.csv${cb}`).then(r => r.ok ? r.text() : ''),
      fetch(`./daily_data/codex_learning_summary.json${cb}`).then(r => r.ok ? r.json() : null),
    ]).then(([s, csv, learning]) => { setSummary(s); setResults(csv ? parseCsv(csv) : []); setCodexLearning(learning); })
      .catch(() => setError('成績データを読み込めませんでした。'));
  }, []);

  const source = SOURCES.find(s => s.key === sourceKey) || SOURCES[0];
  const allRaces = useMemo(() => results.map(r => {
    const rid = String(r.ID || r.RaceID || '');
    const picks = parseStakes(summary[rid]?.[sourceKey]);
    const result = String(r.Result || '').replace(/\s/g, '');
    const payout = Number(r.Payout) || 0;
    const hitPick = picks.find(p => p.combo === result);
    const invest = picks.reduce((n, p) => n + p.stake, 0);
    const ret = hitPick ? hitPick.stake * payout / 100 : 0;
    return { id: rid, date: r.Date || '', venue: r.Venue || '', r: r.R || '', result, picks, invest, ret, hit: !!hitPick };
  }).filter(r => r.picks.length > 0), [results, summary, sourceKey]);

  const races = useMemo(() => {
    if (period === 'total' || allRaces.length === 0) return allRaces;
    const dated = allRaces.map(r => r.date).filter(Boolean).sort();
    if (dated.length === 0) return allRaces;
    const latest = new Date(`${dated[dated.length - 1]}T00:00:00`);
    const days = period === 'weekly' ? 7 : 30;
    const cutoff = new Date(latest);
    cutoff.setDate(cutoff.getDate() - (days - 1));
    return allRaces.filter(r => r.date && new Date(`${r.date}T00:00:00`) >= cutoff);
  }, [allRaces, period]);

  const stats = useMemo(() => {
    const invest = races.reduce((n, r) => n + r.invest, 0);
    const ret = races.reduce((n, r) => n + r.ret, 0);
    return { n: races.length, hits: races.filter(r => r.hit).length, invest, ret, roi: invest ? ret / invest * 100 : 0 };
  }, [races]);
  const trend = useMemo(() => {
    const byDate = races.reduce((map, race) => ({
      ...map,
      [race.date]: {
        date: race.date,
        invest: (map[race.date]?.invest || 0) + race.invest,
        ret: (map[race.date]?.ret || 0) + race.ret,
      },
    }), {});
    return Object.values(byDate)
      .sort((a, b) => a.date.localeCompare(b.date))
      .reduce((rows, day) => {
        const previous = rows[rows.length - 1];
        const totalInvest = (previous?.totalInvest || 0) + day.invest;
        const totalReturn = (previous?.totalReturn || 0) + day.ret;
        return [...rows, {
          date: day.date.slice(5),
          roi: totalInvest ? Math.round(totalReturn / totalInvest * 1000) / 10 : 0,
          totalInvest,
          totalReturn,
        }];
      }, []);
  }, [races]);
  const venue = useMemo(() => Object.values(races.reduce((map, race) => ({
    ...map,
    [race.venue]: {
      venue: race.venue,
      n: (map[race.venue]?.n || 0) + 1,
      hits: (map[race.venue]?.hits || 0) + (race.hit ? 1 : 0),
    },
  }), {})).map(v => ({ ...v, hitRate: Math.round(v.hits / v.n * 1000) / 10 })).sort((a, b) => b.hitRate - a.hitRate), [races]);

  const hitRate = stats.n ? stats.hits / stats.n * 100 : 0;
  const profit = stats.ret - stats.invest;
  const metricCards = [
    { label: 'ROI', value: `${stats.roi.toFixed(1)}%`, note: stats.roi >= 100 ? '投資額を上回っています' : '回収率100%が目安', icon: TrendingUp, tone: stats.roi >= 100 ? 'positive' : 'neutral' },
    { label: '的中率', value: stats.n ? `${hitRate.toFixed(1)}%` : '—', note: `${stats.hits.toLocaleString()} / ${stats.n.toLocaleString()} レース`, icon: Target, tone: 'accent' },
    { label: '収支', value: `${profit >= 0 ? '+' : '-'}¥${Math.abs(Math.round(profit)).toLocaleString()}`, note: `投資 ¥${Math.round(stats.invest).toLocaleString()}`, icon: CircleDollarSign, tone: profit >= 0 ? 'positive' : 'negative' },
    { label: '払戻', value: `¥${Math.round(stats.ret).toLocaleString()}`, note: `${PERIOD_LABEL[period]} の合計`, icon: Activity, tone: 'accent' },
  ];

  const chartAxis = { stroke: '#94a3b8', fontSize: 11, tickLine: false, axisLine: false };
  const tooltipStyle = { backgroundColor: '#0f172a', border: 'none', borderRadius: '12px', color: '#f8fafc', boxShadow: '0 14px 32px rgba(15,23,42,.22)' };

  return <main className="model-dashboard">
    <section className="model-switcher" aria-label="予測モデルを選択">
      <div className="model-switcher-label"><Sparkles size={15} /> モデル別パフォーマンス</div>
      <div className="model-switcher-scroll">
        {SOURCES.map(s => <button key={s.key} className={`model-chip ${s.key === sourceKey ? 'active' : ''}`} style={{ '--model-color': s.color }} onClick={() => setSourceKey(s.key)}>{s.short}</button>)}
      </div>
    </section>

    <section className="model-hero" style={{ '--model-color': source.color }}>
      <div>
        <div className="model-eyebrow"><span className="live-dot" /> {PERIOD_LABEL[period]} / 結果確定済み</div>
        <h2>{source.label}</h2>
        <p>{source.description}</p>
      </div>
      <div className="model-sample"><Database size={17} /><strong>{stats.n.toLocaleString()}</strong><span>レース</span></div>
    </section>
    {sourceKey === 'stakes_codex' && codexLearning && (
      <div className="glass-card learning-card">
        <div style={{ color: '#14b8a6', fontWeight: 700, marginBottom: '0.4rem' }}>Codex 自動フィードバック学習</div>
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.82rem' }}>
          <span>過去結果 <strong>{Number(codexLearning.historical_results_used || 0).toLocaleString()}</strong> レース</span>
          <span>Codex結果確定 <strong>{Number(codexLearning.codex_feedback?.settled_count || 0).toLocaleString()}</strong> レース</span>
          <span>学習対象日 <strong>{codexLearning.target_date || '-'}</strong></span>
          <span>方式 <strong>{codexLearning.strategy_version || 'feedback_v1'}</strong></span>
        </div>
        <div style={{ marginTop: '0.45rem', fontSize: '0.76rem', color: 'var(--text-secondary, #9ca3af)', lineHeight: 1.5 }}>
          類似レースの実結果とCodex自身の失敗傾向を、翌日の予測材料へ自動反映しています。
          {codexLearning.codex_feedback?.status === 'preliminary' && ' Codex固有の成績は200レースまで参考値として扱います。'}
        </div>
      </div>
    )}
    {error && <div className="glass-card" style={{ padding: '1rem' }}>{error}</div>}
    <div className="metric-grid">
      {metricCards.map(({ label, value, note, icon, tone }) => (
        <article className={`metric-card ${tone}`} key={label}>
          <div className="metric-card-head"><span>{label}</span>{React.createElement(icon, { size: 18 })}</div>
          <strong>{value}</strong>
          <small>{note}</small>
        </article>
      ))}
    </div>
    <div className="performance-grid">
      <section className="glass-card performance-chart performance-chart-wide">
        <div className="section-heading"><div><span>PERFORMANCE</span><h3>ROIの推移</h3></div><small>累積回収率</small></div>
        <ResponsiveContainer width="100%" height={280}><AreaChart data={trend} margin={{ top: 8, right: 6, left: -12, bottom: 0 }}><defs><linearGradient id="roiGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={source.color} stopOpacity={0.34} /><stop offset="100%" stopColor={source.color} stopOpacity={0.02} /></linearGradient></defs><CartesianGrid strokeDasharray="3 5" stroke="#e2e8f0" vertical={false} /><XAxis dataKey="date" {...chartAxis} /><YAxis unit="%" {...chartAxis} /><Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, 'ROI']} /><Area type="monotone" dataKey="roi" stroke={source.color} strokeWidth={2.5} fill="url(#roiGradient)" /></AreaChart></ResponsiveContainer>
      </section>
      <section className="glass-card performance-chart">
        <div className="section-heading"><div><span>VENUE</span><h3>会場別的中率</h3></div><small>上位から表示</small></div>
        <ResponsiveContainer width="100%" height={280}><BarChart data={venue.slice(0, 12)} margin={{ top: 8, right: 0, left: -18, bottom: 0 }}><CartesianGrid strokeDasharray="3 5" stroke="#e2e8f0" vertical={false} /><XAxis dataKey="venue" {...chartAxis} /><YAxis unit="%" {...chartAxis} /><Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, '的中率']} /><Bar dataKey="hitRate" fill={source.color} radius={[5, 5, 0, 0]} /></BarChart></ResponsiveContainer>
      </section>
    </div>
    <section className="recent-section">
      <button className="recent-toggle" onClick={() => setRecentOpen(open => !open)} aria-expanded={recentOpen}>
        <span><Activity size={16} /> 直近の確定レース</span><strong>{recentOpen ? '閉じる −' : '表示する ＋'}</strong>
      </button>
      {recentOpen && <div className="recent-list">{[...races].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 20).map(r => <div key={r.id} className={r.hit ? 'recent-race hit' : 'recent-race miss'}><div><strong>{r.venue} {r.r}R</strong><small>{r.date}</small></div><span className="result-badge">{r.hit ? 'HIT' : 'MISS'}</span><span className="race-picks">{r.picks.map(p => p.combo).join(' / ')}</span><strong className={r.ret - r.invest >= 0 ? 'profit' : 'loss'}>{r.ret - r.invest >= 0 ? '+' : '-'}¥{Math.abs(Math.round(r.ret - r.invest)).toLocaleString()}</strong></div>)}</div>}
    </section>
  </main>;
};

export default ModelDashboard;
