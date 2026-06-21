import React, { useEffect, useState } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area,
  BarChart, Bar
} from 'recharts';
import { TrendingUp, Award, DollarSign, Activity } from 'lucide-react';
import Battle from './Battle';
import Toto from './Toto';
import Tendency from './Tendency';
import './index.css';

const App = () => {
  const [data, setData] = useState(null);
  const [loopData, setLoopData] = useState(null);
  const [error, setError] = useState(null);
  const [period, setPeriod] = useState('total'); // 'weekly', 'monthly', 'total'
  const [page, setPage] = useState('dashboard'); // 'dashboard', 'ailab'
  const [expandedRaces, setExpandedRaces] = useState(new Set());

  const toggleReasoning = (id) => {
    setExpandedRaces(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  useEffect(() => {
    // 日次更新データの古いキャッシュを避けるためクエリで打ち消す
    const cb = `?t=${Date.now()}`;
    fetch(`./daily_data/dashboard_data.json${cb}`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        return res.json();
      })
      .then(json => setData(json))
      .catch(err => {
        console.error("Data load error:", err);
        setError(err.message);
      });

    fetch(`./daily_data/loop_results.json${cb}`)
      .then(res => res.ok ? res.json() : null)
      .then(json => json && setLoopData(json))
      .catch(() => {});
  }, []);

  if (error) return (
    <div className="dashboard-container">
      <h1 style={{ color: 'var(--error)' }}>Data Load Error</h1>
      <p style={{ color: 'var(--text-secondary)' }}>{error}</p>
    </div>
  );

  if (!data) return <div className="dashboard-container">Loading Premium Intelligence...</div>;

  const currentStats = data[period];
  
  // 期間に応じたチャートデータのフィルタリング
  const chartData = (() => {
    if (period === 'total') return data.daily_history;
    const days = period === 'weekly' ? 7 : 30;
    return data.daily_history.slice(-days);
  })();

  // AI Labページ
  const renderAiLab = () => (
    <div>
      <div className="glass-card" style={{ marginBottom: '1.5rem', padding: '1.5rem' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.2rem' }}>自己改善ループ サマリー</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>累計試行数</div>
            <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--accent-blue)' }}>{loopData?.total_trials ?? '-'}</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>改善成功</div>
            <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--success)' }}>{loopData?.total_improvements ?? '-'}</div>
          </div>
          {loopData?.best && (
            <>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>最高スコア</div>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--accent-purple)' }}>{Number(loopData.best.composite_score).toFixed(1)}</div>
              </div>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>最高ROI</div>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--success)' }}>{Number(loopData.best.roi).toFixed(1)}%</div>
              </div>
            </>
          )}
        </div>
        {loopData?.best && (
          <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'rgba(99,102,241,0.08)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            🏆 ベスト試行 #{loopData.best.trial_id}: {loopData.best.change_summary}
          </div>
        )}
      </div>

      <div className="glass-card" style={{ padding: '1.5rem' }}>
        <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.2rem' }}>実験ログ（直近50件）</h3>
        {!loopData || loopData.trials.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)' }}>まだ実験データがありません。</p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ borderBottom: '2px solid #e2e8f0' }}>
                  {['#', '日時', 'ROI%', '的中率%', '取引数', 'スコア', '採用', '変更内容'].map(h => (
                    <th key={h} style={{ padding: '0.5rem 0.75rem', textAlign: 'left', color: 'var(--text-secondary)', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[...loopData.trials].reverse().map((t, i) => {
                  const kept = String(t.is_kept) === '1';
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid #f1f5f9', background: kept ? 'rgba(16,185,129,0.04)' : 'transparent' }}>
                      <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-secondary)' }}>{t.trial_id}</td>
                      <td style={{ padding: '0.5rem 0.75rem', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }}>{String(t.timestamp).slice(0, 16)}</td>
                      <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600, color: Number(t.roi) >= 100 ? 'var(--success)' : 'var(--text-primary)' }}>{Number(t.roi).toFixed(1)}</td>
                      <td style={{ padding: '0.5rem 0.75rem' }}>{Number(t.hit_rate).toFixed(1)}</td>
                      <td style={{ padding: '0.5rem 0.75rem' }}>{t.n_trades}</td>
                      <td style={{ padding: '0.5rem 0.75rem', fontWeight: 600, color: 'var(--accent-purple)' }}>{Number(t.composite_score).toFixed(1)}</td>
                      <td style={{ padding: '0.5rem 0.75rem', textAlign: 'center' }}>{kept ? '✅' : '❌'}</td>
                      <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-secondary)', maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={t.change_summary}>{t.change_summary}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="dashboard-container">
      <header className="header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.75rem' }}>
          <h1 style={{ margin: 0 }}>BOAT RACE AI | Premium ROI Dashboard</h1>
          <div className="tab-container">
            <button className={`tab-button ${page === 'dashboard' ? 'active' : ''}`} onClick={() => setPage('dashboard')}>Dashboard</button>
            {/* AI Lab タブは非表示（自己改善ループ停止中のため）。将来AIが賢くなったら復活できるよう
                renderAiLab() と loop_results.json・ループ関連スクリプトはそのまま残してある。
                再表示するにはこの行のコメントを戻すだけ:
            <button className={`tab-button ${page === 'ailab' ? 'active' : ''}`} onClick={() => setPage('ailab')}>AI Lab</button> */}
            <button className={`tab-button ${page === 'battle' ? 'active' : ''}`} onClick={() => setPage('battle')}>予測対戦</button>
            <button className={`tab-button ${page === 'tendency' ? 'active' : ''}`} onClick={() => setPage('tendency')}>傾向</button>
            <button className={`tab-button ${page === 'toto' ? 'active' : ''}`} onClick={() => setPage('toto')}>toto</button>
          </div>
        </div>
        {page === 'dashboard' && (
          <div className="tab-container" style={{ marginTop: '0.75rem' }}>
            {['weekly', 'monthly', 'total'].map(p => (
              <button
                key={p}
                className={`tab-button ${period === p ? 'active' : ''}`}
                onClick={() => setPeriod(p)}
              >
                {p === 'weekly' ? '7 Days' : p === 'monthly' ? '30 Days' : 'All Time'}
              </button>
            ))}
          </div>
        )}
      </header>

      {page === 'ailab' && renderAiLab()}

      {page === 'battle' && <Battle />}

      {page === 'tendency' && <Tendency />}

      {page === 'toto' && <Toto />}

      {page === 'dashboard' && <>
      <div className="stats-grid">
        <div className="glass-card stat-item">
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="stat-label">{period.toUpperCase()} ROI</span>
            <TrendingUp size={20} color="var(--accent-blue)" />
          </div>
          <span className="stat-value" style={{ color: currentStats.roi >= 100 ? 'var(--success)' : 'var(--text-primary)' }}>
            {currentStats.roi}%
          </span>
        </div>
        <div className="glass-card stat-item">
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="stat-label">Hit Rate</span>
            <Award size={20} color="var(--accent-purple)" />
          </div>
          <span className="stat-value">{currentStats.hit_rate}%</span>
        </div>
        <div className="glass-card stat-item">
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="stat-label">Invest</span>
            <Activity size={20} color="var(--text-secondary)" />
          </div>
          <span className="stat-value">¥{currentStats.invest.toLocaleString()}</span>
        </div>
        <div className="glass-card stat-item">
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span className="stat-label">Return</span>
            <DollarSign size={20} color="var(--success)" />
          </div>
          <span className="stat-value">¥{currentStats.return.toLocaleString()}</span>
        </div>
      </div>

      <div className="charts-grid">
        <div className="glass-card chart-container full-width-chart">
          <h3 style={{ margin: '0 0 1.5rem 0', fontSize: '1.2rem' }}>ROI Trends ({period})</h3>
          <ResponsiveContainer width="100%" height="90%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="colorRoi" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--accent-blue)" stopOpacity={0.3}/>
                  <stop offset="95%" stopColor="var(--accent-blue)" stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="date" stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} unit="%" />
              <Tooltip 
                contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.05)' }}
                itemStyle={{ color: 'var(--accent-blue)' }}
              />
              <Area type="monotone" dataKey="roi" stroke="var(--accent-blue)" fillOpacity={1} fill="url(#colorRoi)" strokeWidth={4} />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="glass-card chart-container">
          <h3 style={{ margin: '0 0 1.5rem 0', fontSize: '1.2rem' }}>Venue Hit Rate (All Time)</h3>
          <ResponsiveContainer width="100%" height="90%">
            <BarChart data={data.venue_stats}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="venue" stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} unit="%" />
              <Tooltip cursor={{fill: 'transparent'}} contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px' }} />
              <Bar dataKey="hit_rate" fill="var(--accent-purple)" radius={[4, 4, 0, 0]} name="Hit Rate %" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="glass-card chart-container">
          <h3 style={{ margin: '0 0 1.5rem 0', fontSize: '1.2rem' }}>EV Distribution ROI (All Time)</h3>
          <ResponsiveContainer width="100%" height="90%">
            <BarChart data={data.ev_stats}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="category" stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} />
              <YAxis stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} unit="%" />
              <Tooltip cursor={{fill: 'transparent'}} contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px' }} />
              <Bar dataKey="roi" fill="var(--success)" radius={[4, 4, 0, 0]} name="ROI %" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {data.race_stats && data.race_stats.length > 0 && (
          <div className="glass-card chart-container full-width-chart">
            <h3 style={{ margin: '0 0 1.5rem 0', fontSize: '1.2rem' }}>Race Number Analysis (All Time)</h3>
            <ResponsiveContainer width="100%" height="90%">
              <BarChart data={data.race_stats}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
                <XAxis dataKey="r" stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `${v}R`} />
                <YAxis yAxisId="left" stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} unit="%" />
                <YAxis yAxisId="right" orientation="right" stroke="var(--text-secondary)" fontSize={12} tickLine={false} axisLine={false} unit="%" />
                <Tooltip cursor={{fill: 'transparent'}} contentStyle={{ backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '12px' }} />
                <Bar yAxisId="left" dataKey="hit_rate" fill="var(--accent-blue)" radius={[4, 4, 0, 0]} name="Hit Rate %" />
                <Bar yAxisId="right" dataKey="roi" fill="var(--accent-purple)" radius={[4, 4, 0, 0]} name="ROI %" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="prediction-list">
        <h3 style={{ margin: '1rem 0', fontSize: '1.2rem' }}>Recent Predictions</h3>
        {data.recent_races.map(race => (
          <div key={race.id} className={`race-card ${race.is_hit ? 'hit' : 'miss'}`}>
            <div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{race.date}</div>
              <div style={{ fontWeight: 700 }}>{race.venue} {race.r}R</div>
            </div>
            <div className={`badge ${race.is_hit ? 'badge-hit' : 'badge-miss'}`}>
              {race.is_hit ? '🎯 HIT' : '❌ MISS'}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
              Result: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{race.result_eye}</span>
              <span style={{ marginLeft: '10px', fontSize: '0.8rem', opacity: 0.8 }}>({race.odds}倍)</span>
            </div>
            <div style={{ fontSize: '0.9rem' }}>
              Invest: ¥{race.invest.toLocaleString()}
            </div>
            <div className={race.return > 0 ? 'profit-plus' : 'profit-minus'}>
              {race.return > 0 ? `+¥${(race.return - race.invest).toLocaleString()}` : `-¥${race.invest.toLocaleString()}`}
            </div>
            {race.ai_reasoning && (
              <>
                <button className="toggle-reasoning" onClick={() => toggleReasoning(race.id)}>
                  {expandedRaces.has(race.id) ? '▾ Hide AI Reasoning' : '▸ Show AI Reasoning'}
                </button>
                {expandedRaces.has(race.id) && (
                  <div className="ai-reasoning">
                    {race.ai_reasoning}
                  </div>
                )}
              </>
            )}
          </div>
        ))}
      </div>
      </>}
    </div>
  );
};

export default App;
