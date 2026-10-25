import React, { useEffect, useState } from 'react';

// まとめページ。overview.json（build_overview.py が朝バッチで生成）だけを読む。
// ファイルが無い・古い・一部が集計できない場合も、その部分だけ「集計待ち」にして画面全体は壊さない。

const formatYen = (value, signed = true) => {
  if (value == null) return '—';
  const amount = Math.round(Number(value) || 0);
  const sign = signed ? (amount >= 0 ? '+' : '-') : '';
  return `${sign}¥${Math.abs(amount).toLocaleString()}`;
};
const formatPercent = value => value == null ? '—' : `${Number(value).toFixed(1)}%`;
const shortDate = value => value ? String(value).slice(5).replace('-', '/') : '—';

const STATUS_LABEL = { ok: '正常', partial: '一部欠け', failed: '失敗', pending: 'この後実行' };
const VERDICT_LABEL = {
  accruing: '蓄積中',
  no_difference: '差なし',
  playbook_better: 'ありが優勢',
  baseline_better: 'なしが優勢',
};
const REFLECTOR_LABEL = { claude: 'Claude', codex: 'Codex' };

const unavailable = section => !section || section.status === 'unavailable';

const Waiting = ({ children = '集計待ちです。次回の自動更新後に表示されます。' }) =>
  <div className="ov-empty">{children}</div>;

const StatusPill = ({ status }) =>
  <span className={`ov-pill ov-pill-${status}`}>{STATUS_LABEL[status] || status}</span>;

// 1. 今日の運用チェック
const OpsSection = ({ ops }) => {
  if (unavailable(ops)) return <section className="comparison-table-card"><h3 className="ov-title">今日の運用チェック</h3><Waiting /></section>;
  const alerts = ops.models.filter(model => model.alert);
  return <section className="comparison-table-card">
    <div className="simple-section-heading">
      <div>
        <h3>今日の運用チェック</h3>
        <p>{ops.date} の予測が全モデルそろっているか。2日以上続けて失敗したモデルは赤で表示します。</p>
      </div>
      <span className={`sample-status ${alerts.length ? 'ov-alert-badge' : 'enough'}`}>
        {alerts.length ? `要確認 ${alerts.length}件` : '問題なし'}
      </span>
    </div>
    <div className="ov-ops-grid">
      {ops.models.map(model => <article key={model.key} className={`ov-ops-card ${model.alert ? 'is-alert' : ''} status-${model.status}`}>
        <div className="ov-ops-top">
          <strong>{model.label}</strong>
          <StatusPill status={model.status} />
        </div>
        <div className="ov-ops-count">
          <strong>{model.today_count}</strong><span>/ {model.target_races}レース</span>
        </div>
        <small>
          {model.alert
            ? `${model.fail_streak_days}日連続で失敗（最終成功 ${shortDate(model.last_success_date)}）`
            : `最終成功 ${shortDate(model.last_success_date)}`}
        </small>
      </article>)}
    </div>
    <div className="ov-jobs">
      {(ops.jobs || []).map(job => <div key={job.key} className="ov-job">
        <StatusPill status={job.status} />
        <div><strong>{job.label}</strong><span>{job.detail}</span><small>{job.note}</small></div>
      </div>)}
    </div>
  </section>;
};

// 結論ボードの1マス
const Cell = ({ title, metric, note, empty = '蓄積中' }) => {
  const measured = metric && metric.n > 0;
  return <div className={`ov-cell ${measured ? '' : 'is-empty'}`}>
    <span className="ov-cell-title">{title}</span>
    {measured ? <>
      <strong className={metric.roi_pct >= 100 ? 'value-positive' : ''}>{formatPercent(metric.roi_pct)}</strong>
      <small>当たり除外 {formatPercent(metric.roi_without_largest_win_pct)}</small>
      <small>{metric.n}件・{formatYen(metric.profit_yen)}</small>
    </> : <strong className="ov-cell-empty">{empty}</strong>}
    {note && <small className="ov-cell-note">{note}</small>}
  </div>;
};

// 2. 実験の結論ボード
const BoardSection = ({ board }) => {
  if (unavailable(board)) return <section className="comparison-table-card"><h3 className="ov-title">実験の結論ボード</h3><Waiting /></section>;
  return <section className="comparison-table-card">
    <div className="simple-section-heading">
      <div>
        <h3>実験の結論ボード</h3>
        <p>同じレースで「心得集なし（今まで）」と「心得集あり」を比べます。ROIは100%以上で投資額超え。{board.decision_sample}件たまるまでは優劣を断定しません。</p>
      </div>
    </div>
    <div className="ov-board">
      {board.models.map(row => {
        const diff = row.diff || {};
        return <article key={row.key} className="ov-board-card">
          <div className="ov-board-head">
            <strong>{row.label}</strong>
            <span className={`ov-verdict ov-verdict-${row.verdict}`}>{VERDICT_LABEL[row.verdict] || row.verdict}</span>
          </div>
          <div className={`ov-cells ${row.kind === 'strong' ? 'is-four' : 'is-two'}`}>
            <Cell title="今まで" metric={row.baseline} />
            {row.kind === 'strong' && <Cell title="Jev" metric={row.jev} note="期間が違う参考値" />}
            <Cell title="心得集" metric={row.playbook} empty={row.first_date ? '蓄積中' : '開始前'} />
            {row.kind === 'strong' && <Cell title="心得集＋Jev" metric={row.playbook_jev} note="Jevが1点に絞った場合" />}
          </div>
          <div className="ov-progress">
            <div className="ov-progress-bar"><i style={{ width: `${row.progress_pct || 0}%` }} /></div>
            <span>{diff.n || 0} / {board.decision_sample}件</span>
          </div>
          <small className="ov-diff">
            {diff.n
              ? `1レースあたりの差（あり−なし） ${formatYen(diff.mean_diff_yen)}${diff.ci95 ? ` / 95%区間 ${formatYen(diff.ci95[0])} 〜 ${formatYen(diff.ci95[1])}` : '（30件から区間を表示）'}`
              : '心得集ありの予測がたまると、ここに差が出ます。'}
          </small>
          {row.kind === 'strong' && <small className="ov-diff">
            {row.jev_effect?.diff?.n
              ? `Jev同士の差（心得集＋Jev − Jev） ${formatYen(row.jev_effect.diff.mean_diff_yen)}・${row.jev_effect.diff.n}件${row.jev_effect.diff.ci95 ? ` / 95%区間 ${formatYen(row.jev_effect.diff.ci95[0])} 〜 ${formatYen(row.jev_effect.diff.ci95[1])}` : ''}`
              : 'Jev同士の比較（心得集＋Jev − Jev）は、確定結果がたまると表示します。'}
          </small>}
        </article>;
      })}
    </div>
  </section>;
};

// 3. 心得集の今
const PlaybookSection = ({ playbooks }) => {
  if (unavailable(playbooks)) return <section className="comparison-table-card"><h3 className="ov-title">心得集の今</h3><Waiting /></section>;
  return <section className="comparison-table-card">
    <div className="simple-section-heading">
      <div>
        <h3>心得集の今</h3>
        <p>強いモデルが毎晩結果を振り返り、各モデルの心得を足したり直したりしています。（今週 = {shortDate(playbooks.week_start)}〜）</p>
      </div>
    </div>
    <div className="ov-playbooks">
      {playbooks.models.map(model => {
        const week = model.week_changes || {};
        return <article key={model.key} className="ov-playbook-card">
          <div className="ov-playbook-head">
            <div>
              <strong>{model.label}</strong>
              <small>振り返り役: {REFLECTOR_LABEL[model.reflector] || model.reflector || '—'}</small>
            </div>
            <div className="ov-playbook-count"><strong>{model.active_count ?? '—'}</strong><span>件</span></div>
          </div>
          <div className="ov-week">
            <span>今週 追加 <b>{week.add || 0}</b></span>
            <span>修正 <b>{week.update || 0}</b></span>
            <span>無効 <b>{week.disable || 0}</b></span>
          </div>
          {model.top_items?.length
            ? <ol className="ov-top-items">
              {model.top_items.map(item => <li key={item.id}>
                <p>{item.text}</p>
                <small>使用 {item.n}回・的中 {item.hits}・ROI {formatPercent(item.roi_pct)}</small>
              </li>)}
            </ol>
            : <p className="ov-muted">{model.active_count ? 'まだ使用実績がありません（予測で使われると上位3件が出ます）。' : '心得はまだありません。'}</p>}
        </article>;
      })}
    </div>
  </section>;
};

// 4. 過去30日検証
const BacktestSection = ({ backtest }) => <section className="comparison-table-card">
  <div className="simple-section-heading">
    <div><h3>過去30日の検証</h3><p>9/15〜10/14 の各日の朝の情報だけを使い、心得集あり／なしを同じ条件で再現して比べます。</p></div>
    <span className="sample-status">{backtest?.status === 'done' ? '実施済み' : '未実施'}</span>
  </div>
  {backtest?.status === 'done'
    ? <div className="ov-backtest">
      {['pilot', 'holdout'].map(part => backtest[part] && <div key={part}>
        <span>{part === 'pilot' ? 'パイロット（最初の10日）' : 'ホールドアウト（残り）'}</span>
        <strong>{formatYen(backtest[part].mean_diff_yen)}</strong>
        <small>{backtest[part].ci95 ? `95%区間 ${formatYen(backtest[part].ci95[0])} 〜 ${formatYen(backtest[part].ci95[1])}` : '区間なし'}</small>
      </div>)}
    </div>
    : <p className="ov-muted">{backtest?.note || 'まだ実施していません。'}</p>}
</section>;

// 5. 全体成績の要約
const OverallSection = ({ overall, onOpenModels }) => {
  if (unavailable(overall)) return <section className="comparison-table-card"><h3 className="ov-title">全体成績</h3><Waiting /></section>;
  return <section className="comparison-table-card">
    <div className="simple-section-heading">
      <div><h3>全体成績</h3><p>大当たりを含む実際の収支と、その当たりを除いたストレス結果を分けて表示します。</p></div>
      <button type="button" className="ov-link" onClick={onOpenModels}>モデル比較を見る →</button>
    </div>
    <div className="ov-overall">
      {['weekly', 'monthly'].map(key => {
        const period = overall.periods?.[key];
        if (!period) return null;
        const combined = period.combined || {};
        const assessment = combined.assessment || {};
        return <div key={key} className="ov-overall-card">
          <div className="ov-overall-head">
            <span className="ov-overall-label">{period.label}<small>{shortDate(period.start_date)}〜{shortDate(period.end_date)}</small></span>
            <span className={`ov-assessment ov-assessment-${assessment.code || 'unmeasured'}`}>{assessment.label || '集計待ち'}</span>
          </div>
          <strong className={combined.profit >= 0 ? 'value-positive' : 'value-negative'}>{formatYen(combined.profit)}</strong>
          <small>実投資 {formatYen(combined.invest, false)}・実払戻 {formatYen(combined.return, false)}・的中率 {formatPercent(combined.hit_rate)}</small>
          <div className="ov-stress-grid">
            <div><span>大当たり込みROI</span><strong>{formatPercent(combined.roi)}</strong></div>
            <div><span>最大1件を除く</span><strong>{formatPercent(combined.roi_without_largest_win)}</strong></div>
            <div><span>上位3件を除く</span><strong>{formatPercent(combined.roi_without_top3_wins)}</strong></div>
            <div><span>最大1件の払戻依存</span><strong>{formatPercent(combined.largest_return_share)}</strong></div>
          </div>
          <div className="ov-overall-sample">
            <div className="ov-progress-bar"><i style={{ width: `${assessment.sample_progress_pct || 0}%` }} /></div>
            <span>{assessment.sample_label || '蓄積中'} {combined.n ?? 0} / {overall.decision_sample || 500}延べ予測</span>
          </div>
          <p className="ov-assessment-note">{assessment.note || '次回の集計更新後に再現性を判定します。'}</p>
          <small>最大損失幅 {formatYen(combined.max_drawdown, false)}・最長連敗 {combined.longest_losing_streak ?? '—'}回</small>
          <small>トップ: {period.top_model ? `${period.top_model.label}（${formatYen(period.top_model.profit)}）` : '—'}・黒字 {period.positive_models}/{period.measured_models}モデル</small>
        </div>;
      })}
    </div>
  </section>;
};

const Overview = ({ onOpenModels }) => {
  const [overview, setOverview] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch(`./daily_data/overview.json?t=${Date.now()}`)
      .then(res => res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`)))
      .then(setOverview)
      .catch(() => setFailed(true));
  }, []);

  if (failed) return <main className="model-dashboard ov-page"><Waiting>まとめの集計がまだありません。次回の朝の自動更新後に表示されます。</Waiting></main>;
  if (!overview) return <main className="model-dashboard ov-page"><Waiting>まとめを読み込み中です…</Waiting></main>;

  return <main className="model-dashboard ov-page">
    <section className="comparison-intro">
      <div>
        <span className="comparison-kicker">OVERVIEW</span>
        <h2>まとめ</h2>
        <p>運用状況、実際の収支、高配当への依存、実験の進み具合を1画面で。</p>
      </div>
      <div className="comparison-date">
        <strong>{overview.today}</strong>
        <span>結果確定 {overview.latest_result_date || '—'}・集計 {String(overview.generated_at || '').slice(11, 16)}</span>
      </div>
    </section>
    <OpsSection ops={overview.ops} />
    <BoardSection board={overview.board} />
    <PlaybookSection playbooks={overview.playbooks} />
    <BacktestSection backtest={overview.backtest} />
    <OverallSection overall={overview.overall} onOpenModels={onOpenModels} />
  </main>;
};

export default Overview;
