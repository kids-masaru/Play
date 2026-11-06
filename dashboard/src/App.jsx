import React, { useEffect, useState } from 'react';
import Battle from './Battle';
import Toto from './Toto';
import ModelDashboard from './ModelDashboard';
import Overview from './Overview';
import Experiments from './Experiments';
import './index.css';
import './site-refresh.css';

const NAV_ITEMS = [
  { key: 'overview', label: 'まとめ', icon: 'overview' },
  { key: 'dashboard', label: 'モデル比較', icon: 'models' },
  { key: 'experiments', label: '実験', icon: 'experiments' },
  { key: 'battle', label: '今日の予測', icon: 'boat' },
  { key: 'toto', label: 'toto', icon: 'toto' },
];

const PAGE_META = {
  overview: {
    eyebrow: 'DAILY BRIEFING',
    title: 'いま、どうなっている？',
    description: '運用状況・実収支・実験の進み具合を、まずここで確認します。',
  },
  dashboard: {
    eyebrow: 'MODEL PERFORMANCE',
    title: 'どのモデルが強い？',
    description: '利益、ROI、的中率、損失幅を同じ条件で比べます。',
  },
  experiments: {
    eyebrow: 'DECISION LAB',
    title: '改善は本当に効いた？',
    description: '心得集とJevの効果を、条件を変えずにシャドー比較します。',
  },
  battle: {
    eyebrow: 'BOAT RACE',
    title: '今日のボートレース',
    description: '各モデルの買い目と根拠を並べ、自分の予想も記録できます。',
  },
  toto: {
    eyebrow: 'FOOTBALL TOTO',
    title: 'toto予測',
    description: '統計・市場・AIの見方を並べ、結果が出たら同じ条件で答え合わせします。',
  },
  ailab: {
    eyebrow: 'ARCHIVE',
    title: 'AI Lab',
    description: '停止中の自己改善ループの履歴を確認します。',
  },
};

// 外部アイコンライブラリに依存せず、ナビゲーション用の線画を共通化する。
const NavIcon = ({ name }) => {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' };
  if (name === 'overview') return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><path d="M4 13h6V4H4zM14 20h6V11h-6zM4 20h6v-3H4zM14 7h6V4h-6z" /></svg>;
  if (name === 'models') return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><path d="M4 19V9M10 19V5M16 19v-7M22 19V3" /><path d="M2 19h20" /></svg>;
  if (name === 'experiments') return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3" /><path d="M7.5 15h9" /></svg>;
  if (name === 'boat') return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><path d="m3 14 2 5h14l2-5-9-3zM8 11l1-6h6l1 7" /><path d="M5 22c1.3 0 1.7-1 3-1s1.7 1 3 1 1.7-1 3-1 1.7 1 3 1" /></svg>;
  return <svg viewBox="0 0 24 24" aria-hidden="true" {...common}><path d="M4 5h16v14H4z" /><path d="M8 9h8M8 13h3M14 13h2M8 17h8" /></svg>;
};

const App = () => {
  const [data, setData] = useState(null);
  const [loopData, setLoopData] = useState(null);
  const [error, setError] = useState(null);
  const [period, setPeriod] = useState('weekly'); // 初期表示は直近7日。30日・全期間へ切替可能。
  // 初期表示は「まとめ」（2026-10-17〜）。'overview' / 'dashboard' / 'experiments' / 'battle' / 'toto' / 'ailab'
  const [page, setPage] = useState('overview');

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
    <div className="app-state-screen">
      <span className="app-state-mark">!</span>
      <h1>データを読み込めませんでした</h1>
      <p>{error}</p>
    </div>
  );

  if (!data) return (
    <div className="app-state-screen is-loading">
      <span className="app-loader" aria-hidden="true" />
      <strong>予測データを準備しています</strong>
      <p>最新の集計を読み込み中です。</p>
    </div>
  );

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

  const meta = PAGE_META[page] || PAGE_META.overview;

  return (
    <div className="app-shell dashboard-container">
      <aside className="app-sidebar">
        <button type="button" className="brand-lockup" onClick={() => setPage('overview')} aria-label="まとめを開く">
          <span className="brand-mark">PL</span>
          <span className="brand-copy">
            <span className="brand-kicker">PLAY INTELLIGENCE</span>
            <strong>予測ラボ</strong>
          </span>
        </button>

        <nav className="primary-nav" aria-label="メインメニュー">
          {NAV_ITEMS.map(item => (
            <button
              type="button"
              key={item.key}
              className={`nav-item ${page === item.key ? 'active' : ''}`}
              aria-current={page === item.key ? 'page' : undefined}
              onClick={() => setPage(item.key)}
            >
              <span className="nav-icon"><NavIcon name={item.icon} /></span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-status">
          <span><i className="live-dot" /> DATA READY</span>
          <strong>{data?.latest_result_date || '集計待ち'}</strong>
          <small>最新の確定結果</small>
        </div>
      </aside>

      <div className="app-workspace">
        <header className="workspace-header">
          <div className="page-context">
            <span>{meta.eyebrow}</span>
            <h1>{meta.title}</h1>
            <p>{meta.description}</p>
          </div>
          <div className="workspace-meta">
            <span className="workspace-live"><i className="live-dot" /> 自動集計</span>
            <small>確定結果</small>
            <strong>{data?.latest_result_date || '—'}</strong>
          </div>
        </header>

        {page === 'dashboard' && (
          <section className="dashboard-toolbar" aria-label="モデル比較の期間">
            <div className="dashboard-status">
              <span><i className="status-dot" /> 集計済み</span>
              <span>現役6モデルを同条件で比較</span>
            </div>
            <div className="period-switcher">
              {['weekly', 'monthly', 'total'].map(p => (
                <button
                  type="button"
                  key={p}
                  className={`tab-button ${period === p ? 'active' : ''}`}
                  onClick={() => setPeriod(p)}
                >
                  {p === 'weekly' ? '7日' : p === 'monthly' ? '30日' : '全期間'}
                </button>
              ))}
            </div>
          </section>
        )}

        <div className={`page-content page-${page}`}>
          {page === 'overview' && <Overview onOpenModels={() => setPage('dashboard')} />}
          {page === 'experiments' && <Experiments />}
          {page === 'ailab' && renderAiLab()}
          {page === 'battle' && <Battle />}
          {page === 'toto' && <Toto />}
          {page === 'dashboard' && <ModelDashboard period={period} />}
        </div>
      </div>
    </div>
  );
};

export default App;
