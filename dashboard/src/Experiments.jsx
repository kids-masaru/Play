import React, { useEffect, useState } from 'react';
import { ClvSection, JevPairingSection } from './ModelDashboard';

// 「実験」タブ。実購入には使っていない比較実験（心得集・Jev・CLV）をまとめる。

const formatYen = value => {
  if (value == null) return '—';
  const amount = Math.round(Number(value) || 0);
  return `${amount >= 0 ? '+' : '-'}¥${Math.abs(amount).toLocaleString()}`;
};
const formatPercent = value => value == null ? '—' : `${Number(value).toFixed(1)}%`;

const PlaybookEffectSection = () => {
  const [board, setBoard] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch(`./daily_data/overview.json?t=${Date.now()}`)
      .then(res => res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)))
      .then(json => setBoard(json.board?.models ? json.board : null))
      .catch(() => setFailed(true));
  }, []);

  return <section className="comparison-table-card">
    <div className="simple-section-heading">
      <div>
        <h3>心得集の効果</h3>
        <p>強いモデルが振り返って作った心得集を足した予測（あり）と、今までの予測（なし）を、同じレースだけで比べます。</p>
      </div>
      <span className="sample-status">シャドー実験</span>
    </div>
    {failed || !board
      ? <div className="ov-empty">集計待ちです。次回の朝の自動更新後に表示されます。</div>
      : <div className="ov-effect-list">
        {board.models.map(row => <article key={row.key} className="ov-effect-card">
          <div className="ov-effect-head">
            <strong>{row.label}</strong>
            <span>{row.diff?.n || 0} / {board.decision_sample}件</span>
          </div>
          <div className="ov-effect-grid">
            <span />
            <b>なし</b>
            <b>あり</b>
            <span>ROI</span>
            <strong>{formatPercent(row.baseline?.roi_pct)}</strong>
            <strong className={row.playbook?.roi_pct >= 100 ? 'value-positive' : ''}>{formatPercent(row.playbook?.roi_pct)}</strong>
            <span>当たり除外ROI</span>
            <strong>{formatPercent(row.baseline?.roi_without_largest_win_pct)}</strong>
            <strong>{formatPercent(row.playbook?.roi_without_largest_win_pct)}</strong>
            <span>的中率</span>
            <strong>{formatPercent(row.baseline?.hit_rate_pct)}</strong>
            <strong>{formatPercent(row.playbook?.hit_rate_pct)}</strong>
            <span>収支</span>
            <strong>{row.baseline?.n ? formatYen(row.baseline.profit_yen) : '—'}</strong>
            <strong>{row.playbook?.n ? formatYen(row.playbook.profit_yen) : '—'}</strong>
          </div>
          <small className="ov-diff">
            {row.diff?.ci95
              ? `差（あり−なし）1レースあたり ${formatYen(row.diff.mean_diff_yen)}　95%区間 ${formatYen(row.diff.ci95[0])} 〜 ${formatYen(row.diff.ci95[1])}`
              : row.diff?.n ? `差（あり−なし）1レースあたり ${formatYen(row.diff.mean_diff_yen)}（30件から区間を表示）` : '心得集ありの確定結果がまだありません。'}
          </small>
        </article>)}
      </div>}
  </section>;
};

const Experiments = () => <main className="model-dashboard ov-page">
  <section className="comparison-intro">
    <div>
      <span className="comparison-kicker">EXPERIMENTS</span>
      <h2>実験</h2>
      <p>実購入には反映していない比較実験です。件数がたまるまでは参考値として見てください。</p>
    </div>
  </section>
  <PlaybookEffectSection />
  <JevPairingSection />
  <ClvSection />
</main>;

export default Experiments;
