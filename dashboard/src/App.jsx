import React, { useEffect, useState } from 'react';
import Battle from './Battle';
import Toto from './Toto';
import ModelDashboard from './ModelDashboard';
import './index.css';

const App = () => {
  const [data, setData] = useState(null);
  const [loopData, setLoopData] = useState(null);
  const [error, setError] = useState(null);
  const [period, setPeriod] = useState('weekly'); // 初期表示は直近7日。30日・全期間へ切替可能。
  const [page, setPage] = useState('dashboard'); // 'dashboard', 'ailab'

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
      <header className="header app-header">
        <div className="app-header-top">
          <div className="brand-lockup">
            <span className="brand-mark">BR</span>
            <div><span className="brand-kicker">BOAT RACE</span><h1>予測成績</h1></div>
          </div>
          <nav className="tab-container primary-nav" aria-label="メインメニュー">
            <button className={`tab-button ${page === 'dashboard' ? 'active' : ''}`} onClick={() => setPage('dashboard')}>モデル比較</button>
            {/* AI Lab タブは非表示（自己改善ループ停止中のため）。将来AIが賢くなったら復活できるよう
                renderAiLab() と loop_results.json・ループ関連スクリプトはそのまま残してある。
                再表示するにはこの行のコメントを戻すだけ:
            <button className={`tab-button ${page === 'ailab' ? 'active' : ''}`} onClick={() => setPage('ailab')}>AI Lab</button> */}
            <button className={`tab-button ${page === 'battle' ? 'active' : ''}`} onClick={() => setPage('battle')}>今日の予測</button>
            <button className={`tab-button ${page === 'toto' ? 'active' : ''}`} onClick={() => setPage('toto')}>toto</button>
          </nav>
        </div>
        {page === 'dashboard' && (
          <div className="dashboard-status">
            <span><i className="status-dot" /> 集計済み</span>
            <span>比較対象: 6モデル（基本Gemma・Det除外）</span>
            <span>結果最終日: {data?.latest_result_date || '-'}</span>
          </div>
        )}
        {page === 'dashboard' && (
          <div className="period-switcher">
            {['weekly', 'monthly', 'total'].map(p => (
              <button
                key={p}
                className={`tab-button ${period === p ? 'active' : ''}`}
                onClick={() => setPeriod(p)}
              >
                {p === 'weekly' ? '7日' : p === 'monthly' ? '30日' : '全期間'}
              </button>
            ))}
          </div>
        )}
      </header>

      {page === 'ailab' && renderAiLab()}

      {page === 'battle' && <Battle />}

      {page === 'toto' && <Toto />}

      {page === 'dashboard' && <ModelDashboard period={period} />}
    </div>
  );
};

export default App;
