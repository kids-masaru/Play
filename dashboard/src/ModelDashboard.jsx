import React, { useEffect, useMemo, useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

const PERIOD_LABEL = { weekly: '直近7日', monthly: '直近30日', total: '全期間' };

const formatYen = (value, signed = true) => {
  const amount = Math.round(Number(value) || 0);
  const sign = signed ? (amount >= 0 ? '+' : '-') : '';
  return `${sign}¥${Math.abs(amount).toLocaleString()}`;
};

const formatPercent = value => value == null ? '—' : `${Number(value).toFixed(1)}%`;

const MODEL_ICONS = {
  stakes_gemini: './model-icons/gemini.svg',
  stakes_grok: './model-icons/grok.svg',
  stakes_gemmaft: './model-icons/learned-gemini.svg',
  stakes_gemmaclaude: './model-icons/learned-claude.svg',
  stakes_gemmagrokx: './model-icons/learned-grokx.svg',
  stakes_codex: './model-icons/codex.svg',
  stakes_claude: './model-icons/claude.svg',
};

const Direction = ({ model, period }) => {
  if (!model.n) return <span className="change neutral">計測前</span>;
  if (model.roi_change == null) return <span className="change neutral">比較なし</span>;
  const label = period === 'weekly' ? '前7日比' : period === 'monthly' ? '前30日比' : '前期間比';
  if (model.direction === 'up') return <span className="change up">{label} ↑{model.roi_change.toFixed(1)}pt</span>;
  if (model.direction === 'down') return <span className="change down">{label} ↓{Math.abs(model.roi_change).toFixed(1)}pt</span>;
  return <span className="change neutral">{label} →{model.roi_change >= 0 ? '+' : ''}{model.roi_change.toFixed(1)}pt</span>;
};

const CHARTS = {
  profit: {
    title: '期間内の累積収支',
    description: '最終的に資金が増えているかを確認します。',
    prefix: 'profit_',
    reference: 0,
  },
  rollingRoi: {
    title: '7日移動ROI',
    description: '直近7日だけを切り出し、最近の投資効率が改善しているかを確認します。',
    prefix: 'roi_',
    reference: 100,
  },
  dailyProfit: {
    title: '日別収支',
    description: '利益が継続しているか、一度の大当たりに偏っているかを確認します。',
    prefix: 'daily_profit_',
    reference: 0,
  },
  drawdown: {
    title: '損失幅（ドローダウン）',
    description: '直近の最高収支から、どこまで資金が減ったかを確認します。',
    prefix: 'drawdown_',
    reference: 0,
  },
};

const ModelDashboard = ({ period = 'weekly' }) => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [chartMode, setChartMode] = useState('rollingRoi');
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

  const periodData = data?.periods?.[period];
  const current = useMemo(() => periodData?.dashboard
    ? { ...periodData, ...periodData.dashboard }
    : periodData, [periodData]);
  const chartModels = useMemo(() => current ? [
    { key: 'combined', short: '全モデル合計', color: '#111827' },
    ...current.models
      .filter(model => model.n > 0)
      .map(model => ({ key: model.key, short: model.short, color: model.color })),
  ] : [], [current]);
  const visibleChartModels = chartMode === 'dailyProfit'
    ? chartModels.filter(model => model.key === mobileModel)
    : isCompact
      ? chartModels.filter(model => model.key === 'combined' || model.key === mobileModel)
      : chartModels;

  if (error) return <div className="comparison-empty">{error}</div>;
  if (!current) return <div className="comparison-empty">モデル成績を読み込み中です…</div>;

  const combined = current.combined;
  const measuredModels = current.models.filter(model => model.n > 0);
  const positiveModels = measuredModels.filter(model => model.profit > 0).length;
  const improvingModels = measuredModels.filter(model => model.direction === 'up').length;
  const leader = measuredModels[0];
  const growthCandidate = [...current.models]
    .filter(model => model.roi_change != null && model.roi_change > 0 && model.n >= 30)
    .sort((a, b) => b.roi_change - a.roi_change)[0];
  const comparisonLabel = period === 'weekly' ? '前7日比' : period === 'monthly' ? '前30日比' : '前期間比';
  const chart = CHARTS[chartMode];
  const chartIsPercent = chartMode === 'rollingRoi';

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
        <div><span>最大損失幅</span><strong className="value-negative">{formatYen(combined.max_drawdown, false)}</strong><small>期間中の最大下落幅</small></div>
        <div className="combined-invest"><span>総投資</span><strong>{formatYen(combined.invest, false)}</strong><small>延べ{combined.n}予測</small></div>
      </div>
    </section>

    <section className="comparison-summary-line" aria-label="期間の要約">
      <span className="summary-signal leader"><small>今いちばん良い</small><strong>{leader?.short || '—'} · {leader ? formatYen(leader.profit) : '—'}</strong></span>
      <span className="summary-signal growth"><small>上向き候補</small><strong>{growthCandidate?.short || '該当なし'}{growthCandidate ? ` · ${comparisonLabel} +${growthCandidate.roi_change.toFixed(1)}pt` : ''}</strong></span>
      <span className="summary-signal context"><small>全体の様子</small><strong>黒字 {positiveModels}/{measuredModels.length}・改善 {improvingModels}モデル</strong></span>
    </section>

    <section className="comparison-table-card">
      <div className="simple-section-heading">
        <div><h3>モデル別ランキング</h3><p>収支が高い順。的中率だけでなく、ROIと最大損失も合わせて判断します。</p></div>
      </div>
      <div className="model-ranking-list">
        {current.models.map(model => <article className="model-ranking-card" key={model.key}>
          <div className="model-card-top">
            <img className="model-icon" src={MODEL_ICONS[model.key]} alt="" />
            <strong className="model-card-name">{model.label}</strong>
            <strong className={`model-card-profit ${model.n ? (model.profit >= 0 ? 'value-positive' : 'value-negative') : ''}`}>{model.n ? formatYen(model.profit) : '計測前'}</strong>
            <Direction model={model} period={period} />
          </div>
          <div className="model-card-metrics">
            <div><span>ROI</span><strong className={model.roi >= 100 ? 'value-positive' : ''}>{formatPercent(model.roi)}</strong></div>
            <div><span>的中率</span><strong>{formatPercent(model.hit_rate)}</strong><small>{model.hits}/{model.n}</small></div>
            <div><span>最大損失幅</span><strong className={model.n ? 'value-negative' : ''}>{model.n ? formatYen(model.max_drawdown, false) : '—'}</strong></div>
          </div>
        </article>)}
      </div>
    </section>

    <section className="comparison-chart-card">
      <div className="simple-section-heading chart-heading">
        <div><h3>{chart.title}</h3><p>{chart.description}</p></div>
        <div className="simple-segmented">
          <button className={chartMode === 'profit' ? 'active' : ''} onClick={() => setChartMode('profit')}>累積収支</button>
          <button className={chartMode === 'rollingRoi' ? 'active' : ''} onClick={() => setChartMode('rollingRoi')}>7日移動ROI</button>
          <button className={chartMode === 'dailyProfit' ? 'active' : ''} onClick={() => setChartMode('dailyProfit')}>日別収支</button>
          <button className={chartMode === 'drawdown' ? 'active' : ''} onClick={() => setChartMode('drawdown')}>損失幅</button>
        </div>
      </div>
      <label className={`chart-model-filter ${isCompact || chartMode === 'dailyProfit' ? 'visible' : ''}`}>
        <span>グラフに表示するモデル</span>
        <select value={mobileModel} onChange={event => setMobileModel(event.target.value)}>
          {chartModels.map(model => <option key={model.key} value={model.key}>{model.short}</option>)}
        </select>
      </label>
      {current.trend.length ? <ResponsiveContainer width="100%" height={isCompact ? 280 : 360}>
        <ComposedChart data={current.trend} margin={{ top: 12, right: isCompact ? 2 : 18, left: isCompact ? -16 : 12, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 5" stroke="#e5e7eb" vertical={false} />
          <XAxis dataKey="label" stroke="#6b7280" fontSize={11} tickLine={false} axisLine={false} minTickGap={26} />
          <YAxis stroke="#6b7280" fontSize={11} tickLine={false} axisLine={false} width={62} tickFormatter={value => chartIsPercent ? `${value}%` : `${Math.round(value / 1000)}千`} />
          <Tooltip contentStyle={{ background: '#fff', border: '1px solid #d1d5db', borderRadius: 8, color: '#111827' }} formatter={(value, name) => [chartIsPercent ? formatPercent(value) : formatYen(value), name]} />
          <Legend wrapperStyle={{ fontSize: 12, paddingTop: 10 }} />
          <ReferenceLine y={chart.reference} stroke="#9ca3af" strokeDasharray="5 5" />
          {visibleChartModels.map(model => chartMode === 'dailyProfit'
            ? <Bar key={model.key} dataKey={`${chart.prefix}${model.key}`} name={model.short} fill={model.color} radius={[3, 3, 0, 0]} maxBarSize={34} />
            : <Line
              key={model.key}
              type="monotone"
              dataKey={`${chart.prefix}${model.key}`}
              name={model.short}
              stroke={model.color}
              strokeWidth={model.key === 'combined' ? 3.5 : 1.8}
              strokeOpacity={model.key === 'combined' ? 1 : 0.78}
              dot={false}
              connectNulls={false}
            />)}
        </ComposedChart>
      </ResponsiveContainer> : <div className="comparison-empty">この期間の確定結果はまだありません。</div>}
    </section>
  </main>;
};

export default ModelDashboard;
