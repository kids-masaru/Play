import React, { useEffect, useState } from 'react';
import { 
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area 
} from 'recharts';
import { TrendingUp, Award, DollarSign, Activity } from 'lucide-react';
import './index.css';

const App = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [period, setPeriod] = useState('total'); // 'weekly', 'monthly', 'total'

  useEffect(() => {
    fetch('./daily_data/dashboard_data.json')
      .then(res => {
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        return res.json();
      })
      .then(json => setData(json))
      .catch(err => {
        console.error("Data load error:", err);
        setError(err.message);
      });
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

  return (
    <div className="dashboard-container">
      <header className="header">
        <h1>BOAT RACE AI | Premium ROI Dashboard</h1>
        <div className="tab-container">
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
      </header>

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

      <div className="glass-card chart-container">
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
          </div>
        ))}
      </div>
    </div>
  );
};

export default App;
