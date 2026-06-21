import React, { useEffect, useState } from 'react';
import { Map, Info, Flame, Anchor } from 'lucide-react';

// ============================================================
// 傾向（攻略図）タブ
// ------------------------------------------------------------
// 会場別・レース番号別の「1号艇1着率(イン逃げ率)」をヒートマップで表示。
// 母数の大きい指標なので偏りはノイズでなく本物。予想時の“地形図”として使う。
// データ: daily_data/boat_tendency.json（analysis/boat_venue_tendency.py が生成）
// ============================================================

// イン率(%) → 色。堅い(高い)=緑、荒れる(低い)=赤。おおむね 40〜72% を想定。
const inColor = (v) => {
  if (v == null) return 'rgba(255,255,255,0.06)';
  const lo = 42, hi = 70;
  const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
  const hue = t * 130; // 0=赤 → 130=緑
  return `hsl(${hue}, 62%, 42%)`;
};

const Cell = ({ top, big, sub, sub2, bg, title, minWidth }) => (
  <div title={title} style={{
    background: bg, borderRadius: '8px', padding: '0.5rem 0.4rem', textAlign: 'center',
    color: '#fff', minWidth: minWidth || '60px', border: '1px solid rgba(255,255,255,0.08)',
  }}>
    {top && <div style={{ fontSize: '0.72rem', opacity: 0.92, fontWeight: 600 }}>{top}</div>}
    <div style={{ fontSize: '1.05rem', fontWeight: 800, lineHeight: 1.25 }}>{big}</div>
    {sub && <div style={{ fontSize: '0.64rem', opacity: 0.85 }}>{sub}</div>}
    {sub2 && <div style={{ fontSize: '0.64rem', opacity: 0.85 }}>{sub2}</div>}
  </div>
);

const Legend = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', fontSize: '0.74rem', color: 'var(--text-secondary, #9ca3af)' }}>
    <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}><Anchor size={13} /> 堅い(イン逃げ多い)</span>
    <span style={{ display: 'flex', height: '12px', width: '160px', borderRadius: '6px',
      background: `linear-gradient(90deg, ${inColor(42)}, ${inColor(56)}, ${inColor(70)})` }} />
    <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}><Flame size={13} /> 荒れる(波乱多い)</span>
  </div>
);

const Tendency = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const cb = `?t=${Date.now()}`;
    fetch(`./daily_data/boat_tendency.json${cb}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(`HTTP ${res.status}`)))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, []);

  if (error) return (
    <div className="glass-card" style={{ padding: '1.5rem' }}>
      傾向データ取得エラー: {error}
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.5rem' }}>
        ※ boat_tendency.json が未生成の可能性。`python analysis/boat_venue_tendency.py` を実行してください。
      </div>
    </div>
  );
  if (!data) return <div className="glass-card" style={{ padding: '1.5rem' }}>Loading...</div>;

  const ov = data.overall || {};

  return (
    <div>
      <div style={{ marginBottom: '1.25rem' }}>
        <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <Map size={22} /> 傾向（攻略図）
        </h2>
        <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.2rem' }}>
          1号艇1着率（イン逃げ率）で見る会場・レースの“地形図”。集計期間 {data.date_from}〜{data.date_to}・全{ov.races?.toLocaleString()}レース。
        </div>
      </div>

      {/* 全体サマリ */}
      <div className="glass-card" style={{ padding: '1rem 1.25rem', marginBottom: '1.25rem', display: 'flex', gap: '1.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)' }}>全体イン率</div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#10b981' }}>{ov.in_rate}%</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)' }}>Det本命1着率</div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#a78bfa' }}>{ov.det_in_rate ?? '—'}%</div>
          <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary, #6b7280)' }}>対象{ov.det_races}戦</div>
        </div>
        <div style={{ flex: 1, minWidth: '220px', fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', lineHeight: 1.6 }}>
          <Info size={13} style={{ verticalAlign: '-2px' }} /> Det本命1着率({ov.det_in_rate}%)が全体イン率({ov.in_rate}%)とほぼ同じ＝
          モデルは「ほぼ1号艇を買っているだけ」でイン率以上の上積みがほぼ無い、という意味。
        </div>
      </div>

      {/* レース番号別 */}
      <div className="glass-card" style={{ padding: '1rem 1.1rem', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.6rem' }}>
          <h3 style={{ margin: 0, fontSize: '1rem' }}>レース番号別 イン率</h3>
          <Legend />
        </div>
        <div style={{ display: 'flex', gap: '0.4rem', overflowX: 'auto', paddingBottom: '0.3rem' }}>
          {data.races.map((r) => (
            <Cell key={r.r}
              top={`${r.r}R`}
              big={`${r.in_rate}%`}
              sub={`${r.races}戦`}
              bg={inColor(r.in_rate)}
              minWidth="58px"
              title={`${r.r}R: イン率${r.in_rate}% / ${r.races}レース / 中央払戻¥${r.med_payout.toLocaleString()}`}
            />
          ))}
        </div>
        <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.6rem', lineHeight: 1.6 }}>
          後半レースほど1号艇が堅い（12R＝{data.races.find((x) => x.r === 12)?.in_rate}%）。
          ただし<b>「1着が堅い」＝「儲かる」ではない</b>（みんな知っている→オッズが安い）点に注意。
        </div>
      </div>

      {/* 会場別 */}
      <div className="glass-card" style={{ padding: '1rem 1.1rem', marginBottom: '1.25rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.6rem' }}>
          <h3 style={{ margin: 0, fontSize: '1rem' }}>会場別 イン率（堅い→荒れる順）</h3>
          <Legend />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(74px, 1fr))', gap: '0.4rem' }}>
          {data.venues.map((v) => (
            <Cell key={v.venue}
              top={v.venue}
              big={`${v.in_rate}%`}
              sub={`${v.races}戦`}
              bg={inColor(v.in_rate)}
              title={`${v.venue}: イン率${v.in_rate}% / ${v.races}レース / 中央払戻¥${v.med_payout.toLocaleString()} / Det本命1着率${v.det_in_rate ?? '—'}%`}
            />
          ))}
        </div>
        <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.6rem', lineHeight: 1.6 }}>
          緑＝イン逃げが堅い堅実な会場（徳山・下関など）、赤＝波乱が多い会場（戸田・鳴門など）。
          セルにマウスを乗せると中央払戻・Det本命1着率も出ます。
        </div>
      </div>

      <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary, #6b7280)', lineHeight: 1.7 }}>
        ※ イン率＝1号艇が1着になった割合。母数が大きい（全{ov.races?.toLocaleString()}レース）ので偶然ではなく実際の傾向です。
        中央払戻は3連単（平均値は高配当1本で歪むため中央値を採用）。
      </div>
    </div>
  );
};

export default Tendency;
