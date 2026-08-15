import React, { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity, CircleDollarSign, Database, Sparkles, Target, TrendingUp } from 'lucide-react';

const SOURCES = [
  { key: 'stakes', label: '通常予測', short: '通常', color: '#6366f1', description: 'gemma4:e2b による通常運用' },
  { key: 'stakes_gemini', label: 'Gemini', short: 'Gemini', color: '#059669', description: 'Gemini が出走表と直前情報から判断' },
  { key: 'stakes_grok', label: 'Grok', short: 'Grok', color: '#7c3aed', description: 'Grok がレース情報を読んで予測' },
  { key: 'stakes_gemmaft', label: '学習Gemma（Gemini先生）', short: '学Gemini', color: '#db2777', description: 'Gemini教師データで学習した Gemma' },
  { key: 'stakes_gemmaclaude', label: '学習Gemma（Claude先生）', short: '学Claude', color: '#0891b2', description: 'Claude教師データで学習した Gemma' },
  { key: 'stakes_gemmagrokx', label: '学習Gemma（Grok+X先生）', short: '学Grok+X', color: '#ea580c', description: 'GrokとX情報を教師に学習した Gemma' },
  { key: 'stakes_codex', label: 'Codex', short: 'Codex', color: '#0d9488', description: '過去の結果から自動フィードバックする Codex' },
];

const TREND_METRICS = [
  { key: 'roi', label: 'ROI', title: '累積ROI', unit: '%', reference: 100 },
  { key: 'profit', label: '収支', title: '累積収支', unit: '円', reference: 0 },
  { key: 'hitRate', label: '的中率', title: '累積的中率', unit: '%', reference: null },
  { key: 'dailyHits', label: '日別的中件数', title: '日別的中件数', unit: '件', reference: null, daily: true },
  { key: 'dailyReturnAmount', label: '日別的中金額', title: '日別払戻金額', unit: '円', reference: null, daily: true },
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

const buildRaces = (results, summary, sourceKey) => results.map(r => {
  const rid = String(r.ID || r.RaceID || '');
  const picks = parseStakes(summary[rid]?.[sourceKey]);
  const result = String(r.Result || '').replace(/\s/g, '');
  const payout = Number(r.Payout) || 0;
  const hitPick = picks.find(p => p.combo === result);
  const invest = picks.reduce((n, p) => n + p.stake, 0);
  const ret = hitPick ? hitPick.stake * payout / 100 : 0;
  return { id: rid, date: r.Date || '', venue: r.Venue || '', r: r.R || '', result, picks, invest, ret, hit: !!hitPick };
}).filter(r => r.picks.length > 0);

const filterRacesByPeriod = (races, period, latestDate) => {
  if (period === 'total' || !latestDate) return races;
  const days = period === 'weekly' ? 7 : 30;
  const cutoff = new Date(`${latestDate}T00:00:00`);
  cutoff.setDate(cutoff.getDate() - (days - 1));
  return races.filter(r => r.date && new Date(`${r.date}T00:00:00`) >= cutoff);
};

const buildTrend = (races) => {
  const byDate = races.reduce((map, race) => ({
    ...map,
    [race.date]: {
      dateKey: race.date,
      invest: (map[race.date]?.invest || 0) + race.invest,
      ret: (map[race.date]?.ret || 0) + race.ret,
      races: (map[race.date]?.races || 0) + 1,
      hits: (map[race.date]?.hits || 0) + (race.hit ? 1 : 0),
    },
  }), {});

  return Object.values(byDate)
    .sort((a, b) => a.dateKey.localeCompare(b.dateKey))
    .reduce((rows, day) => {
      const previous = rows[rows.length - 1];
      const totalInvest = (previous?.totalInvest || 0) + day.invest;
      const totalReturn = (previous?.totalReturn || 0) + day.ret;
      const totalRaces = (previous?.totalRaces || 0) + day.races;
      const totalHits = (previous?.hits || 0) + day.hits;
      return [...rows, {
        dateKey: day.dateKey,
        date: day.dateKey.slice(5),
        roi: totalInvest ? Math.round(totalReturn / totalInvest * 1000) / 10 : 0,
        profit: Math.round(totalReturn - totalInvest),
        hitRate: totalRaces ? Math.round(totalHits / totalRaces * 1000) / 10 : 0,
        dailyHits: day.hits,
        dailyReturnAmount: Math.round(day.ret),
        totalInvest,
        totalReturn,
        totalRaces,
      }];
    }, []);
};

const formatMetricValue = (value, metric) => {
  if (value == null) return '—';
  if (metric.unit === '円') return `${Number(value) >= 0 ? '' : '-'}¥${Math.abs(Math.round(Number(value))).toLocaleString()}`;
  if (metric.unit === '%') return `${Number(value).toFixed(1)}%`;
  return `${Math.round(Number(value)).toLocaleString()}件`;
};

const formatAxisValue = (value, metric) => {
  const number = Number(value) || 0;
  if (metric.unit === '円') {
    if (Math.abs(number) >= 10000) return `${Math.round(number / 1000)}千`;
    return Math.round(number).toLocaleString();
  }
  return metric.unit === '%' ? `${number}%` : Math.round(number).toLocaleString();
};

const ModelDashboard = ({ period = 'total' }) => {
  const [sourceKey, setSourceKey] = useState('stakes');
  const [summary, setSummary] = useState({});
  const [results, setResults] = useState([]);
  const [codexLearning, setCodexLearning] = useState(null);
  const [error, setError] = useState('');
  const [recentOpen, setRecentOpen] = useState(false);
  const [trendMetricKey, setTrendMetricKey] = useState('roi');

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
  const latestDate = useMemo(() => results.map(r => r.Date || '').filter(Boolean).sort().at(-1) || '', [results]);
  const racesBySource = useMemo(() => Object.fromEntries(SOURCES.map(s => [
    s.key,
    filterRacesByPeriod(buildRaces(results, summary, s.key), period, latestDate),
  ])), [results, summary, period, latestDate]);
  const races = useMemo(() => racesBySource[sourceKey] || [], [racesBySource, sourceKey]);

  const stats = useMemo(() => {
    const invest = races.reduce((n, r) => n + r.invest, 0);
    const ret = races.reduce((n, r) => n + r.ret, 0);
    return { n: races.length, hits: races.filter(r => r.hit).length, invest, ret, roi: invest ? ret / invest * 100 : 0 };
  }, [races]);
  const trendsBySource = useMemo(() => Object.fromEntries(SOURCES.map(s => [s.key, buildTrend(racesBySource[s.key] || [])])), [racesBySource]);
  const trendMetric = TREND_METRICS.find(metric => metric.key === trendMetricKey) || TREND_METRICS[0];
  const comparisonTrend = useMemo(() => {
    const dates = [...new Set(Object.values(trendsBySource).flatMap(rows => rows.map(row => row.dateKey)))].sort();
    const latestBySource = {};
    const rowBySourceAndDate = Object.fromEntries(SOURCES.map(s => [
      s.key,
      Object.fromEntries((trendsBySource[s.key] || []).map(row => [row.dateKey, row])),
    ]));
    return dates.map(dateKey => {
      const row = { dateKey, date: dateKey.slice(5) };
      SOURCES.forEach(s => {
        const dayRow = rowBySourceAndDate[s.key][dateKey];
        if (trendMetric.daily) {
          row[s.key] = dayRow?.[trendMetricKey] ?? null;
        } else {
          latestBySource[s.key] = dayRow || latestBySource[s.key];
          row[s.key] = latestBySource[s.key]?.[trendMetricKey] ?? null;
        }
      });
      return row;
    });
  }, [trendsBySource, trendMetric, trendMetricKey]);
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
    <section className="trend-controls" aria-label="推移グラフの指標を選択">
      <div>
        <strong>推移指標</strong>
        <small>{trendMetric.daily ? '各日の実績を棒グラフで比較します' : '表示期間内の初日から累積して比較します'}</small>
      </div>
      <div className="trend-metric-tabs">
        {TREND_METRICS.map(metric => (
          <button
            key={metric.key}
            className={metric.key === trendMetricKey ? 'active' : ''}
            onClick={() => setTrendMetricKey(metric.key)}
          >
            {metric.label}
          </button>
        ))}
      </div>
    </section>
    <section className="glass-card performance-chart comparison-chart">
      <div className="section-heading">
        <div><span>ALL MODELS</span><h3>全モデル比較：{trendMetric.title}</h3></div>
        <small>同じ期間・同じ計算基準</small>
      </div>
      <div className="comparison-legend" aria-label="比較モデル一覧">
        {SOURCES.map(s => <span key={s.key}><i style={{ backgroundColor: s.color }} />{s.short}</span>)}
      </div>
      <ResponsiveContainer width="100%" height={340}>
        {trendMetric.daily ? (
          <BarChart data={comparisonTrend} margin={{ top: 12, right: 14, left: 4, bottom: 0 }} barGap={1}>
            <CartesianGrid strokeDasharray="3 5" stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="date" {...chartAxis} />
            <YAxis {...chartAxis} tickFormatter={value => formatAxisValue(value, trendMetric)} width={58} allowDecimals={false} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value, key) => [formatMetricValue(value, trendMetric), SOURCES.find(s => s.key === key)?.short || key]}
            />
            {SOURCES.map(s => <Bar key={s.key} dataKey={s.key} name={s.short} fill={s.color} radius={[3, 3, 0, 0]} maxBarSize={16} />)}
          </BarChart>
        ) : (
          <LineChart data={comparisonTrend} margin={{ top: 12, right: 14, left: 4, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 5" stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="date" {...chartAxis} />
            <YAxis {...chartAxis} tickFormatter={value => formatAxisValue(value, trendMetric)} width={58} />
            <Tooltip
              contentStyle={tooltipStyle}
              formatter={(value, key) => [formatMetricValue(value, trendMetric), SOURCES.find(s => s.key === key)?.short || key]}
            />
            {trendMetric.reference != null && <ReferenceLine y={trendMetric.reference} stroke="#94a3b8" strokeDasharray="5 5" />}
            {SOURCES.map(s => <Line key={s.key} type="monotone" dataKey={s.key} name={s.short} stroke={s.color} strokeWidth={2.2} dot={false} connectNulls={false} />)}
          </LineChart>
        )}
      </ResponsiveContainer>
      <p className="chart-note">{trendMetric.daily
        ? '棒の高さが、その日に的中した件数・金額です。予測自体がない日は棒を表示しません。'
        : '予測がない日より前は線を表示せず、予測開始後にデータがない日は直前の累積値を維持します。'}</p>
    </section>
    <section className="recent-section">
      <button className="recent-toggle" onClick={() => setRecentOpen(open => !open)} aria-expanded={recentOpen}>
        <span><Activity size={16} /> 直近の確定レース</span><strong>{recentOpen ? '閉じる −' : '表示する ＋'}</strong>
      </button>
      {recentOpen && <div className="recent-list">{[...races].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 20).map(r => <div key={r.id} className={r.hit ? 'recent-race hit' : 'recent-race miss'}><div><strong>{r.venue} {r.r}R</strong><small>{r.date}</small></div><span className="result-badge">{r.hit ? 'HIT' : 'MISS'}</span><span className="race-picks">{r.picks.map(p => p.combo).join(' / ')}</span><strong className={r.ret - r.invest >= 0 ? 'profit' : 'loss'}>{r.ret - r.invest >= 0 ? '+' : '-'}¥{Math.abs(Math.round(r.ret - r.invest)).toLocaleString()}</strong></div>)}</div>}
    </section>
  </main>;
};

export default ModelDashboard;
