import React, { useEffect, useMemo, useState } from 'react';
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const PERIOD_LABEL = { weekly: '直近7日', monthly: '直近30日', total: '全期間' };

const formatYen = (value, signed = true) => {
  const amount = Math.round(Number(value) || 0);
  const sign = signed ? (amount >= 0 ? '+' : '-') : '';
  return `${sign}¥${Math.abs(amount).toLocaleString()}`;
};

const formatPercent = value => value == null ? '—' : `${Number(value).toFixed(1)}%`;

const Direction = ({ model }) => {
  if (model.roi_change == null) return <span className="change neutral">比較なし</span>;
  if (model.direction === 'up') return <span className="change up">↑ {model.roi_change.toFixed(1)}pt</span>;
  if (model.direction === 'down') return <span className="change down">↓ {Math.abs(model.roi_change).toFixed(1)}pt</span>;
  return <span className="change neutral">→ {model.roi_change >= 0 ? '+' : ''}{model.roi_change.toFixed(1)}pt</span>;
};

const ModelDashboard = ({ period = 'weekly' }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [chartMode, setChartMode] = useState('profit');
  const [mobileModel, setMobileModel] = useState('combined');
  const [isCompact, setIsCompact] = useState(() => window.matchMedia('(max-width: 760px)').matches);

  useEffect(() => {
    const cb = `?t=${Date.now()}`;
    fetch(`./daily_data/model_performance.json${cb}`)
      .then(response => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then(setData)
      .catch(() => setError('モデル比較データを読み込めませんでした。次回の自動更新後にもう一度お試しください。'));
  }, []);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)');
    const handleChange = event => setIsCompact(event.matches);
    media.addEventListener('change', handleChange);
    return () => media.removeEventListener('change', handleChange);
  }, []);

  const current = data?.periods?.[period];
  const chartModels = useMemo(() => current ? [
    { key: 'combined', short: '全モデル合計', color: '#111827' },
    ...current.models.map(model => ({ key: model.key, short: model.short, color: model.color })),
  ] : [], [current]);
  const visibleChartModels = isCompact
    ? chartModels.filter(model => model.key === 'combined' || model.key === mobileModel)
    : chartModels;

  if (error) return <div className="comparison-empty">{error}</div>;
  if (!current) return <div className="comparison-empty">モデル成績を読み込み中です…</div>;

  const combined = current.combined;
  const positiveModels = current.models.filter(model => model.profit > 0).length;
  const improvingModels = current.models.filter(model => model.direction === 'up').length;
  const leader = current.models[0];
  const chartPrefix = chartMode === 'profit' ? 'profit_' : 'roi_';
  const chartTitle = chartMode === 'profit' ? '期間内の累積収支' : '7日移動ROI';
  const chartReference = chartMode === 'profit' ? 0 : 100;

  return <main className="model-dashboard model-dashboard-simple">
    <section className="comparison-intro">
      <div>
        <span className="comparison-kicker">MODEL PERFORMANCE</span>
        <h2>モデル比較</h2>
        <p>利益・投資効率・損失の大きさを、同じ期間と計算方法で比較します。</p>
      </div>
      <div className="comparison-date">
        <strong>{PERIOD_LABEL[period]}</strong>
        <span>{current.start_date || '開始'} 〜 {current.end_date || '—'}</span>
      </div>
    </section>

    <section className="combined-panel">
      <div className="combined-heading">
        <div><span>全モデル合計</span><small>重複買い目もモデルごとに別口で計算</small></div>
        <strong className={combined.profit >= 0 ? 'value-positive' : 'value-negative'}>{formatYen(combined.profit)}</strong>
      </div>
      <div className="combined-metrics">
        <div><span>ROI</span><strong className={combined.roi >= 100 ? 'value-positive' : ''}>{formatPercent(combined.roi)}</strong><small>100%以上で投資額超え</small></div>
        <div><span>的中率</span><strong>{formatPercent(combined.hit_rate)}</strong><small>{combined.hits} / {combined.n}予測</small></div>
        <div><span>最大ドローダウン</span><strong className="value-negative">{formatYen(combined.max_drawdown, false)}</strong><small>期間中の最大下落幅</small></div>
        <div><span>総投資</span><strong>{formatYen(combined.invest, false)}</strong><small>延べ{combined.n}予測</small></div>
      </div>
    </section>

    <section className="comparison-summary-line" aria-label="期間の要約">
      <span>収支1位 <strong>{leader?.short || '—'}（{leader ? formatYen(leader.profit) : '—'}）</strong></span>
      <span>黒字モデル <strong>{positiveModels} / {current.models.length}</strong></span>
      <span>前期間よりROI改善 <strong>{improvingModels}モデル</strong></span>
    </section>

    <section className="comparison-table-card">
      <div className="simple-section-heading">
        <div><h3>モデル別ランキング</h3><p>収支が高い順。的中率だけでなく、ROIと最大損失も合わせて判断します。</p></div>
      </div>
      <div className="comparison-table-wrap">
        <table className="comparison-table">
          <thead><tr>
            <th>順位</th><th>モデル</th><th>収支</th><th>ROI</th><th>的中率</th><th>対象数</th><th>最大損失幅</th><th>前期間比</th><th>信頼度</th>
          </tr></thead>
          <tbody>
            {current.models.map(model => <tr key={model.key}>
              <td data-label="順位" className="rank-cell">{model.rank}</td>
              <td data-label="モデル"><span className="model-name"><i style={{ background: model.color }} />{model.label}</span></td>
              <td data-label="収支" className={model.profit >= 0 ? 'value-positive' : 'value-negative'}><strong>{formatYen(model.profit)}</strong></td>
              <td data-label="ROI" className={model.roi >= 100 ? 'value-positive' : ''}><strong>{formatPercent(model.roi)}</strong></td>
              <td data-label="的中率">{formatPercent(model.hit_rate)}<small>{model.hits}/{model.n}</small></td>
              <td data-label="対象数">{model.n.toLocaleString()}R</td>
              <td data-label="最大損失幅" className="value-negative">{formatYen(model.max_drawdown, false)}</td>
              <td data-label="前期間比"><Direction model={model} /></td>
              <td data-label="信頼度"><span className={`sample-status ${model.sample_status === '十分' ? 'enough' : ''}`}>{model.sample_status}</span></td>
            </tr>)}
          </tbody>
        </table>
      </div>
    </section>

    <section className="comparison-chart-card">
      <div className="simple-section-heading chart-heading">
        <div><h3>{chartTitle}</h3><p>{chartMode === 'profit' ? '上向きなら、実際の資金が増えています。' : '固定7日間で、最近の投資効率が改善しているかを見ます。'}</p></div>
        <div className="simple-segmented">
          <button className={chartMode === 'profit' ? 'active' : ''} onClick={() => setChartMode('profit')}>累積収支</button>
          <button className={chartMode === 'rollingRoi' ? 'active' : ''} onClick={() => setChartMode('rollingRoi')}>7日移動ROI</button>
        </div>
      </div>
      <label className="mobile-chart-filter">
        <span>グラフに表示するモデル</span>
        <select value={mobileModel} onChange={event => setMobileModel(event.target.value)}>
          {chartModels.map(model => <option key={model.key} value={model.key}>{model.short}</option>)}
        </select>
      </label>
      {current.trend.length ? <ResponsiveContainer width="100%" height={isCompact ? 280 : 360}>
        <LineChart data={current.trend} margin={{ top: 12, right: isCompact ? 2 : 18, left: isCompact ? -16 : 12, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 5" stroke="#e5e7eb" vertical={false} />
          <XAxis dataKey="label" stroke="#6b7280" fontSize={11} tickLine={false} axisLine={false} minTickGap={26} />
          <YAxis stroke="#6b7280" fontSize={11} tickLine={false} axisLine={false} width={62} tickFormatter={value => chartMode === 'profit' ? `${Math.round(value / 1000)}千` : `${value}%`} />
          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, color: '#111827' }} formatter={(value, name) => [chartMode === 'profit' ? formatYen(value) : formatPercent(value), name]} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
          <ReferenceLine y={chartReference} stroke="#9ca3af" strokeDasharray="5 5" />
          {visibleChartModels.map(model => <Line
            key={model.key}
            type="monotone"
            dataKey={`${chartPrefix}${model.key}`}
            name={model.short}
            stroke={model.color}
            strokeWidth={model.key === 'combined' ? 3.5 : 1.8}
            strokeOpacity={model.key === 'combined' ? 1 : 0.78}
            dot={false}
            connectNulls={false}
          />)}
        </LineChart>
      </ResponsiveContainer> : <div className="comparison-empty">この期間の確定結果はまだありません。</div>}
    </section>

    <section className="how-to-read">
      <h3>この画面の見方</h3>
      <p><strong>収支</strong>が最終結果、<strong>ROI</strong>が投資効率です。最大ドローダウンは、途中でどれほど資金が減る可能性があったかを示します。前期間比と7日移動ROIが継続して上向くモデルほど、学習改善の候補として追いやすくなります。</p>
      <p>短期間の大当たりだけで順位が上がることもあるため、「対象数が十分か」「最大損失が大きすぎないか」も一緒に確認してください。</p>
      <div className="learning-status-note">
        <strong>自動学習の現状</strong>
        <span>毎週月曜、新しい結果がある場合に基本予測内のLightGBMを再学習し、旧モデル以上の精度なら更新します。Gemini・Grok・Codexと3種類の学習Gemmaは、現在は成績比較の対象であり、日々の結果から自動で再学習する仕組みにはつながっていません。</span>
      </div>
    </section>
  </main>;
};

export default ModelDashboard;
