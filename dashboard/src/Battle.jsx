import React, { useEffect, useState, useMemo } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend
} from 'recharts';
import { Trophy, Target, Brain, ChevronLeft, Save, Trash2, Cloud, CloudOff, KeyRound, LogOut, TrendingUp, ListOrdered } from 'lucide-react';
import {
  cloudEnabled, hashPassphrase,
  getStoredPass, setStoredPass, clearStoredPass,
  loadPredictions, savePrediction, clearAll, migrateLocalToCloud,
} from './battleStore';

/** AI予測 stakes 文字列をパース ("1-2-3:100, 1-2-4:200" 等の想定) */
const parseAiPicks = (stakesStr) => {
  if (!stakesStr) return [];
  return stakesStr.split(/[,、]/).map(s => {
    const t = s.trim();
    if (!t) return null;
    const m = t.match(/(\d-\d-\d)\s*[:：]?\s*(\d+)?/);
    if (!m) return null;
    return { combo: m[1], stake: m[2] ? parseInt(m[2], 10) : null };
  }).filter(Boolean);
};

/** combo の的中判定 (resultは"1-2-3"形式) */
const isHit = (combo, result) => combo && result && combo === result;

/** 主要セクション: レース一覧 */
const RaceList = ({ races, userPreds, onSelect }) => {
  const userByRid = Object.fromEntries(userPreds.map(p => [p.race_id, p]));
  return (
    <div style={{ display: 'grid', gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
      {races.map(race => {
        const detPicks = parseAiPicks(race.ai_picks_det);
        const llmPicks = parseAiPicks(race.ai_picks_llm);
        const gemPicks = parseAiPicks(race.ai_picks_gemini);
        const hasUser = !!userByRid[race.race_id];
        const aiRow = (label, color, picks) => (
          <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.2rem' }}>
            <span style={{ color, fontWeight: 600, minWidth: '46px' }}>{label}</span>
            <span style={{ fontFamily: 'monospace', color: picks.length ? 'var(--text-primary, #f3f4f6)' : 'var(--text-secondary, #6b7280)' }}>
              {picks.length ? picks.slice(0, 2).map(p => p.combo).join(', ') + (picks.length > 2 ? ' …' : '') : 'なし'}
            </span>
          </div>
        );
        return (
          <div
            key={race.race_id}
            onClick={() => onSelect(race.race_id)}
            className="glass-card"
            style={{
              padding: '1rem',
              cursor: 'pointer',
              borderLeft: hasUser ? '3px solid var(--success, #10b981)' : '3px solid var(--accent-blue, #6366f1)',
              transition: 'transform 0.15s',
            }}
            onMouseOver={e => e.currentTarget.style.transform = 'translateY(-2px)'}
            onMouseOut={e => e.currentTarget.style.transform = 'none'}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
              <strong style={{ fontSize: '1rem' }}>{race.venue} {race.r}R</strong>
              {hasUser && (
                <span style={{ fontSize: '0.75rem', color: 'var(--success, #10b981)' }}>✓ 予想済み</span>
              )}
            </div>
            <div style={{ fontSize: '0.8rem' }}>
              {aiRow('Det', '#60a5fa', detPicks)}
              {aiRow('LLM', '#f59e0b', llmPicks)}
              {aiRow('Gemini', '#10b981', gemPicks)}
            </div>
          </div>
        );
      })}
    </div>
  );
};

/** 主要セクション: レース詳細 */
const RaceDetail = ({ race, userPred, onSave, onBack }) => {
  const aiDet = parseAiPicks(race.ai_picks_det);
  const aiLlm = parseAiPicks(race.ai_picks_llm);
  const aiGem = parseAiPicks(race.ai_picks_gemini);

  const [picks, setPicks] = useState(userPred?.picks?.join(', ') || '');
  const [stake, setStake] = useState(userPred?.stake || '');
  const [confidence, setConfidence] = useState(userPred?.confidence || 3);
  const [note, setNote] = useState(userPred?.note || '');
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    const picksArr = picks.split(/[,、]/).map(s => s.trim()).filter(s => /^\d-\d-\d$/.test(s));
    if (picksArr.length === 0) {
      alert('買い目を「1-2-3, 1-2-4」のように入力してください');
      return;
    }
    const newPred = {
      race_id: race.race_id,
      date: race.date,
      venue: race.venue,
      r: race.r,
      picks: picksArr,
      stake: stake ? parseInt(stake, 10) : null,
      confidence,
      note: note.trim(),
      timestamp: new Date().toISOString(),
    };
    onSave(newPred);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  return (
    <div>
      <button
        onClick={onBack}
        style={{
          display: 'flex', alignItems: 'center', gap: '0.25rem',
          padding: '0.5rem 0.75rem', marginBottom: '1rem',
          background: 'transparent', border: '1px solid var(--border, #374151)',
          borderRadius: '6px', cursor: 'pointer', color: 'var(--text-primary, #f3f4f6)',
        }}
      >
        <ChevronLeft size={16} /> 一覧に戻る
      </button>

      <div className="glass-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
        <h2 style={{ margin: '0 0 0.25rem 0' }}>{race.venue} {race.r}R</h2>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
          {race.date}　天候: {race.weather || '-'}　風: {race.wind_dir || '-'} {race.wind_speed || ''}　波: {race.wave || '-'}　水温: {race.water_temp || '-'}
        </div>
      </div>

      {/* 各艇テーブル */}
      <div className="glass-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
        <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05rem' }}>各艇情報</h3>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', fontSize: '0.85rem', borderCollapse: 'collapse', minWidth: '600px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border, #374151)' }}>
                <th style={{ textAlign: 'left', padding: '0.4rem' }}>艇</th>
                <th style={{ textAlign: 'left', padding: '0.4rem' }}>選手</th>
                <th style={{ textAlign: 'left', padding: '0.4rem' }}>級</th>
                <th style={{ textAlign: 'right', padding: '0.4rem' }}>勝率</th>
                <th style={{ textAlign: 'right', padding: '0.4rem' }}>体重</th>
                <th style={{ textAlign: 'right', padding: '0.4rem' }}>展示</th>
                <th style={{ textAlign: 'right', padding: '0.4rem' }}>Tilt</th>
                <th style={{ textAlign: 'right', padding: '0.4rem' }}>モーター</th>
              </tr>
            </thead>
            <tbody>
              {race.boats.map(b => (
                <tr key={b.lane} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                  <td style={{ padding: '0.4rem', fontWeight: 600 }}>{b.lane}</td>
                  <td style={{ padding: '0.4rem' }}>{b.name}</td>
                  <td style={{ padding: '0.4rem' }}>{b.rank}</td>
                  <td style={{ padding: '0.4rem', textAlign: 'right' }}>{b.win_rate?.toFixed(2) ?? '-'}</td>
                  <td style={{ padding: '0.4rem', textAlign: 'right' }}>{b.weight || '-'}</td>
                  <td style={{ padding: '0.4rem', textAlign: 'right' }}>{b.ex_time?.toFixed(2) ?? '-'}</td>
                  <td style={{ padding: '0.4rem', textAlign: 'right' }}>{b.tilt?.toFixed(1) ?? '-'}</td>
                  <td style={{ padding: '0.4rem', textAlign: 'right' }}>{b.motor_no || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* AI予測 */}
      <div className="glass-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
        <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <Brain size={18} /> AI予測
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
          <div style={{ padding: '0.5rem', background: 'rgba(96,165,250,0.07)', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#60a5fa', marginBottom: '0.25rem', fontWeight: 600 }}>Det (LightGBM)</div>
            <div style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
              {aiDet.length > 0
                ? aiDet.map((p, i) => <div key={i}>{p.combo}{p.stake ? `  ¥${p.stake}` : ''}</div>)
                : '(なし)'}
            </div>
          </div>
          <div style={{ padding: '0.5rem', background: 'rgba(245,158,11,0.07)', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#f59e0b', marginBottom: '0.25rem', fontWeight: 600 }}>LLM (Gemma)</div>
            <div style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
              {aiLlm.length > 0
                ? aiLlm.map((p, i) => <div key={i}>{p.combo}{p.stake ? `  ¥${p.stake}` : ''}</div>)
                : '(なし)'}
            </div>
          </div>
          <div style={{ padding: '0.5rem', background: 'rgba(16,185,129,0.07)', borderRadius: '6px' }}>
            <div style={{ fontSize: '0.8rem', color: '#10b981', marginBottom: '0.25rem', fontWeight: 600 }}>Gemini</div>
            <div style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
              {aiGem.length > 0
                ? aiGem.map((p, i) => <div key={i}>{p.combo}{p.stake ? `  ¥${p.stake}` : ''}</div>)
                : '(なし)'}
            </div>
          </div>
        </div>
        {race.ai_prediction && (
          <details open style={{ marginTop: '0.75rem', borderTop: '1px solid var(--border, #374151)', paddingTop: '0.75rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600, color: 'var(--accent-purple, #a78bfa)' }}>
              💬 AI(LLM/Gemma)の最終見解
            </summary>
            <div style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap', fontSize: '0.85rem', lineHeight: 1.7, color: 'var(--text-primary, #f3f4f6)' }}>
              {race.ai_prediction}
            </div>
          </details>
        )}
        {race.ai_log && (
          <details style={{ marginTop: '0.75rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
              🔍 AI(LLM)の思考プロセス (長文)
            </summary>
            <div style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap', fontSize: '0.8rem', lineHeight: 1.6, color: 'var(--text-secondary, #9ca3af)' }}>
              {race.ai_log}
            </div>
          </details>
        )}
        {race.ai_prediction_gemini && (
          <details open style={{ marginTop: '0.75rem', borderTop: '1px solid var(--border, #374151)', paddingTop: '0.75rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600, color: '#10b981' }}>
              ✨ AI(Gemini)の最終見解
            </summary>
            <div style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap', fontSize: '0.85rem', lineHeight: 1.7, color: 'var(--text-primary, #f3f4f6)' }}>
              {race.ai_prediction_gemini}
            </div>
          </details>
        )}
        {race.ai_log_gemini && (
          <details style={{ marginTop: '0.75rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
              💭 AI(Gemini)の思考プロセス
            </summary>
            <div style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap', fontSize: '0.85rem', lineHeight: 1.7, color: 'var(--text-secondary, #d1d5db)' }}>
              {race.ai_log_gemini}
            </div>
          </details>
        )}
      </div>

      {/* オッズ */}
      <div className="glass-card" style={{ padding: '1.25rem', marginBottom: '1rem' }}>
        <h3 style={{ margin: '0 0 0.5rem 0', fontSize: '1.05rem' }}>3連単オッズ (低い順 上位{race.odds_top.length})</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))', gap: '0.4rem', fontSize: '0.85rem' }}>
          {race.odds_top.map(o => (
            <div key={o.combo} style={{ padding: '0.3rem 0.5rem', background: 'rgba(255,255,255,0.04)', borderRadius: '4px', display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ fontFamily: 'monospace' }}>{o.combo}</span>
              <span style={{ color: 'var(--accent-blue, #60a5fa)' }}>{o.odds.toFixed(1)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 予測入力フォーム */}
      <div className="glass-card" style={{ padding: '1.25rem', border: '2px solid var(--accent-purple, #8b5cf6)' }}>
        <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <Target size={18} /> あなたの予測
        </h3>
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          <div>
            <label style={{ fontSize: '0.85rem', display: 'block', marginBottom: '0.25rem' }}>買い目 (カンマ区切り、例: 1-2-3, 1-2-4)</label>
            <input
              type="text"
              value={picks}
              onChange={e => setPicks(e.target.value)}
              placeholder="1-2-3, 1-2-4"
              style={{ width: '100%', padding: '0.5rem', background: 'rgba(0,0,0,0.3)', color: 'inherit', border: '1px solid var(--border, #374151)', borderRadius: '6px', fontFamily: 'monospace' }}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
            <div>
              <label style={{ fontSize: '0.85rem', display: 'block', marginBottom: '0.25rem' }}>想定金額 (任意)</label>
              <input
                type="number"
                value={stake}
                onChange={e => setStake(e.target.value)}
                placeholder="100"
                style={{ width: '100%', padding: '0.5rem', background: 'rgba(0,0,0,0.3)', color: 'inherit', border: '1px solid var(--border, #374151)', borderRadius: '6px' }}
              />
            </div>
            <div>
              <label style={{ fontSize: '0.85rem', display: 'block', marginBottom: '0.25rem' }}>自信度: {confidence}</label>
              <input
                type="range"
                min={1} max={5} step={1}
                value={confidence}
                onChange={e => setConfidence(parseInt(e.target.value, 10))}
                style={{ width: '100%' }}
              />
            </div>
          </div>
          <div>
            <label style={{ fontSize: '0.85rem', display: 'block', marginBottom: '0.25rem' }}>メモ (任意)</label>
            <textarea
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder="例: 1号艇強い、展示タイム上位"
              rows={2}
              style={{ width: '100%', padding: '0.5rem', background: 'rgba(0,0,0,0.3)', color: 'inherit', border: '1px solid var(--border, #374151)', borderRadius: '6px', resize: 'vertical' }}
            />
          </div>
          <button
            onClick={handleSave}
            style={{
              padding: '0.6rem 1rem', background: 'var(--accent-purple, #8b5cf6)',
              color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer',
              fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem',
            }}
          >
            <Save size={16} /> {saved ? '保存しました ✓' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
};

/** AI予測×結果を突き合わせた「決着済みレース」配列を作る（戦績/グラフ/一覧で共用）。
 *  ユーザーの予測有無に関係なく AI/計算(Det) は常に対象。ユーザーは予測した分だけ混ぜる。 */
const buildSettled = (history, aiPredsByRid, userPreds) => {
  const histByRid = Object.fromEntries(history.map(h => [h.ID, h]));
  const userByRid = Object.fromEntries(userPreds.map(p => [p.race_id, p]));
  return Object.entries(aiPredsByRid).map(([rid, ai]) => {
    const h = histByRid[rid];
    if (!h || !String(h.Result).trim()) return null;
    const result = String(h.Result).replace(/\s/g, '');
    const detPicks = parseAiPicks(ai.stakes_det).map(x => x.combo);
    const llmPicks = parseAiPicks(ai.stakes).map(x => x.combo);
    const gemPicks = parseAiPicks(ai.stakes_gemini).map(x => x.combo);
    const u = userByRid[rid];
    return {
      rid,
      date: h.Date || '', venue: h.Venue || '', r: h.R || '',
      result,
      detPicks, llmPicks, gemPicks,
      detHit: detPicks.length > 0 && detPicks.some(c => c === result),
      llmHit: llmPicks.length > 0 && llmPicks.some(c => c === result),
      gemHit: gemPicks.length > 0 && gemPicks.some(c => c === result),
      hasUser: !!u,
      userPicks: u ? u.picks : [],
      userHit: u ? u.picks.some(c => c === result) : false,
    };
  }).filter(Boolean);
};

/** 履歴サマリパネル: 4者(Det/LLM/Gemini/あなた)比較 */
const HistorySummary = ({ settled }) => {
  const total = settled.length;
  const stat = (predicate) => {
    const evaluable = settled.filter(predicate.has);
    const n = evaluable.length;
    const h = evaluable.filter(predicate.hit).length;
    return {
      n,
      hits: h,
      rate: n > 0 ? (h / n * 100).toFixed(1) : '-',
    };
  };

  const userStat = stat({ has: s => s.hasUser, hit: s => s.userHit });
  const detStat = stat({ has: s => s.detPicks.length > 0, hit: s => s.detHit });
  const llmStat = stat({ has: s => s.llmPicks.length > 0, hit: s => s.llmHit });
  const gemStat = stat({ has: s => s.gemPicks.length > 0, hit: s => s.gemHit });

  return (
    <div className="glass-card" style={{ padding: '1.25rem', marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Trophy size={18} /> 4者対戦戦績 (AI比較は結果が出た{total}レース／あなたは予想した{userStat.n}レース)
      </h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.85rem' }}>
        <CompetitorCard
          name="AI Det (LightGBM)"
          color="#60a5fa"
          rate={detStat.rate}
          hits={detStat.hits}
          n={detStat.n}
        />
        <CompetitorCard
          name="AI LLM (Gemma)"
          color="#f59e0b"
          rate={llmStat.rate}
          hits={llmStat.hits}
          n={llmStat.n}
        />
        <CompetitorCard
          name="AI Gemini"
          color="#10b981"
          rate={gemStat.rate}
          hits={gemStat.hits}
          n={gemStat.n}
        />
        <CompetitorCard
          name="あなた"
          color="#8b5cf6"
          rate={userStat.rate}
          hits={userStat.hits}
          n={userStat.n}
          highlight
        />
      </div>
      {total === 0 ? (
        <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
          まだ結果データがありません。
        </div>
      ) : userStat.n === 0 && (
        <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
          AI/計算の戦績は常に集計中です。あなたが予想を入れたレースだけ「あなた」の的中にも反映されます。
        </div>
      )}
    </div>
  );
};

const CompetitorCard = ({ name, color, rate, hits, n, highlight }) => (
  <div style={{
    padding: '0.85rem',
    background: highlight ? `${color}15` : 'rgba(255,255,255,0.03)',
    border: `1px solid ${color}40`,
    borderRadius: '8px',
    textAlign: 'center',
  }}>
    <div style={{ fontSize: '0.8rem', color, marginBottom: '0.4rem', fontWeight: 600 }}>{name}</div>
    <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'inherit' }}>{rate}%</div>
    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)' }}>
      {hits}/{n} 的中
    </div>
  </div>
);

const Stat = ({ label, value, accent }) => (
  <div style={{ textAlign: 'center' }}>
    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>{label}</div>
    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: accent ? 'var(--accent-blue, #60a5fa)' : 'inherit' }}>{value}</div>
  </div>
);

const TREND_AXIS = { stroke: 'var(--text-secondary, #9ca3af)', fontSize: 11, tickLine: false, axisLine: false };
const TREND_TIP = { backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: '0.8rem' };

/** 月別 的中率の推移（折れ線） */
const HitRateTrend = ({ settled }) => {
  const byMonth = {};
  settled.forEach(s => {
    const m = (s.date || '').slice(0, 7); // YYYY-MM
    if (!m) return;
    const b = byMonth[m] || (byMonth[m] = { month: m, dN: 0, dH: 0, lN: 0, lH: 0, gN: 0, gH: 0, uN: 0, uH: 0 });
    if (s.detPicks.length) { b.dN++; if (s.detHit) b.dH++; }
    if (s.llmPicks.length) { b.lN++; if (s.llmHit) b.lH++; }
    if (s.gemPicks.length) { b.gN++; if (s.gemHit) b.gH++; }
    if (s.hasUser) { b.uN++; if (s.userHit) b.uH++; }
  });
  const data = Object.values(byMonth)
    .sort((a, b) => a.month.localeCompare(b.month))
    .map(b => ({
      month: b.month.slice(2), // 'YY-MM'
      Det: b.dN ? Math.round(b.dH / b.dN * 100) : null,
      LLM: b.lN ? Math.round(b.lH / b.lN * 100) : null,
      Gemini: b.gN ? Math.round(b.gH / b.gN * 100) : null,
      あなた: b.uN ? Math.round(b.uH / b.uN * 100) : null,
    }));
  if (data.length === 0) return null;
  return (
    <div className="glass-card" style={{ padding: '1rem 1.1rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <TrendingUp size={18} /> 月別 的中率の推移
      </h3>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
          <XAxis dataKey="month" {...TREND_AXIS} />
          <YAxis unit="%" {...TREND_AXIS} />
          <Tooltip contentStyle={TREND_TIP} formatter={(v) => v == null ? ['-', ''] : [`${v}%`, '']} />
          <Legend wrapperStyle={{ fontSize: '0.78rem' }} />
          <Line dataKey="Det" stroke="#60a5fa" connectNulls dot={false} strokeWidth={2} />
          <Line dataKey="LLM" stroke="#f59e0b" connectNulls dot={false} strokeWidth={2} />
          <Line dataKey="Gemini" stroke="#10b981" connectNulls dot={false} strokeWidth={2} />
          <Line dataKey="あなた" stroke="#8b5cf6" connectNulls dot={{ r: 3 }} strokeWidth={2.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

/** 過去レースの予想と結果（新しい順、もっと見るで追加表示） */
const PastRaces = ({ settled }) => {
  const [limit, setLimit] = useState(50);
  const sorted = [...settled].sort((a, b) =>
    `${b.date}_${b.venue}_${String(b.r).padStart(2, '0')}`.localeCompare(`${a.date}_${a.venue}_${String(a.r).padStart(2, '0')}`));
  const shown = sorted.slice(0, limit);

  const Pick = ({ picks, hit }) => {
    if (!picks || picks.length === 0) return <span style={{ color: 'var(--text-secondary, #6b7280)' }}>-</span>;
    return <span style={{ color: hit ? '#10b981' : 'var(--text-secondary, #9ca3af)', fontWeight: hit ? 700 : 400 }}>
      {picks[0]}{hit ? ' ✓' : ''}
    </span>;
  };
  const th = { padding: '0.4rem 0.5rem', textAlign: 'left', color: 'var(--text-secondary, #9ca3af)', fontWeight: 600, whiteSpace: 'nowrap' };
  const td = { padding: '0.4rem 0.5rem', whiteSpace: 'nowrap', fontFamily: 'monospace' };

  return (
    <div className="glass-card" style={{ padding: '1rem 1.1rem' }}>
      <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <ListOrdered size={18} /> 過去レースの予想と結果（{settled.length}件）
      </h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem', minWidth: '560px' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border, #374151)' }}>
              {['日付', 'レース', '結果', 'Det', 'LLM', 'Gemini', 'あなた'].map(h => <th key={h} style={th}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {shown.map(s => (
              <tr key={s.rid} style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <td style={{ ...td, color: 'var(--text-secondary, #9ca3af)' }}>{s.date}</td>
                <td style={td}>{s.venue}{s.r}R</td>
                <td style={{ ...td, fontWeight: 700, color: 'var(--accent-blue, #60a5fa)' }}>{s.result}</td>
                <td style={td}><Pick picks={s.detPicks} hit={s.detHit} /></td>
                <td style={td}><Pick picks={s.llmPicks} hit={s.llmHit} /></td>
                <td style={td}><Pick picks={s.gemPicks} hit={s.gemHit} /></td>
                <td style={td}>{s.hasUser ? <Pick picks={s.userPicks} hit={s.userHit} /> : <span style={{ color: 'var(--text-secondary, #6b7280)' }}>-</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {limit < sorted.length && (
        <button onClick={() => setLimit(l => l + 50)} style={{ marginTop: '0.75rem', padding: '0.45rem 1rem', background: 'transparent', border: '1px solid var(--border, #374151)', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-primary, #f3f4f6)', fontSize: '0.85rem' }}>
          もっと見る（残り {sorted.length - limit} 件）
        </button>
      )}
    </div>
  );
};

/** 合言葉バー: クラウド同期の有効化 / 状態表示 */
const PassphraseBar = ({ passReady, statusMsg, onSetPass, onLogout }) => {
  const [val, setVal] = useState('');

  // Firebase 未設定（プレースホルダのまま）＝この端末のみ保存
  if (!cloudEnabled()) {
    return (
      <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)' }}>
        <CloudOff size={15} /> この端末にのみ保存中（クラウド未設定）
      </div>
    );
  }

  // 合言葉 未設定 → 入力フォーム
  if (!passReady) {
    return (
      <div className="glass-card" style={{ padding: '0.85rem 1rem', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.4rem' }}>
          <KeyRound size={16} /> 合言葉でクラウド同期
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.5rem' }}>
          合言葉を入れると複数の端末で予測を共有できます（各端末で同じ合言葉を1回入力）。
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="password"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') onSetPass(val); }}
            placeholder="合言葉"
            style={{ flex: 1, padding: '0.5rem', background: 'rgba(0,0,0,0.3)', color: 'inherit', border: '1px solid var(--border, #374151)', borderRadius: '6px' }}
          />
          <button
            onClick={() => onSetPass(val)}
            style={{ padding: '0.5rem 1rem', background: 'var(--accent-purple, #8b5cf6)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
          >設定</button>
        </div>
      </div>
    );
  }

  // 合言葉 設定済み → 同期中表示
  return (
    <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', color: 'var(--success, #10b981)' }}>
        <Cloud size={15} /> {statusMsg || 'クラウド同期中'}
      </span>
      <button
        onClick={onLogout}
        title="この端末で合言葉を解除"
        style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.35rem 0.6rem', background: 'transparent', border: '1px solid var(--border, #374151)', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.78rem' }}
      >
        <LogOut size={13} /> 解除
      </button>
    </div>
  );
};

/** トップレベルコンポーネント */
const Battle = () => {
  const [info, setInfo] = useState(null);
  const [history, setHistory] = useState([]);
  const [aiPreds, setAiPreds] = useState({});
  const [error, setError] = useState(null);
  const [selectedRid, setSelectedRid] = useState(null);
  const [userPreds, setUserPreds] = useState([]);
  // 合言葉(uid)とクラウド状態
  const [uid, setUid] = useState('');
  const [passReady, setPassReady] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');
  const [view, setView] = useState('today'); // 'today' = 今日のレース / 'past' = 過去成績

  // AI予測×結果の決着済みレース（戦績カード・グラフ・一覧で共用）。重い結合なのでメモ化。
  const settled = useMemo(
    () => buildSettled(history, aiPreds, userPreds),
    [history, aiPreds, userPreds]
  );

  // ユーザー予測のロード（uid があればクラウド、無ければローカル）
  const reloadUserPreds = async (theUid) => {
    if (cloudEnabled() && theUid) {
      const moved = await migrateLocalToCloud(theUid);
      const arr = await loadPredictions(theUid);
      setUserPreds(arr);
      setStatusMsg(moved > 0 ? `クラウド同期中（${moved}件をこの端末から移行）` : 'クラウド同期中');
    } else {
      const arr = await loadPredictions(null);
      setUserPreds(arr);
      setStatusMsg('');
    }
  };

  // 初回: 保存済み合言葉があれば復元してロード
  useEffect(() => {
    const saved = getStoredPass();
    if (cloudEnabled() && saved) {
      hashPassphrase(saved).then((h) => {
        setUid(h);
        setPassReady(true);
        reloadUserPreds(h);
      });
    } else {
      reloadUserPreds(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetch('./daily_data/daily_race_info.json')
      .then(res => res.ok ? res.json() : Promise.reject(`HTTP ${res.status}`))
      .then(setInfo)
      .catch(err => setError(String(err)));

    // AI予測サマリ (全期間、Det/LLM picks)
    fetch('./daily_data/ai_predictions_summary.json')
      .then(res => res.ok ? res.json() : {})
      .then(setAiPreds)
      .catch(() => {});

    // 履歴は CSV を簡易パース
    fetch('./daily_data/daily_history_results.csv')
      .then(res => res.ok ? res.text() : '')
      .then(text => {
        if (!text) return;
        const lines = text.split('\n').filter(l => l.trim());
        const headers = lines[0].split(',').map(h => h.trim());
        const idx = (name) => headers.indexOf(name);
        const iID = idx('ID'), iRes = idx('Result'), iPay = idx('Payout');
        const iDate = idx('Date'), iVenue = idx('Venue'), iR = idx('R');
        const rows = lines.slice(1).map(l => {
          const cols = l.split(',');
          return {
            ID: cols[iID],
            Result: cols[iRes],
            Payout: cols[iPay],
            Date: iDate >= 0 ? cols[iDate] : '',
            Venue: iVenue >= 0 ? cols[iVenue] : '',
            R: iR >= 0 ? cols[iR] : '',
          };
        });
        setHistory(rows);
      })
      .catch(() => {});
  }, []);

  const handleSavePred = (newPred) => {
    // 即時にUI反映（楽観更新）→ 裏でローカル+クラウドへ永続化
    const updated = userPreds.filter(p => p.race_id !== newPred.race_id);
    updated.push(newPred);
    setUserPreds(updated);
    savePrediction(uid, newPred);
  };

  const handleClearAll = async () => {
    if (!confirm('あなたの予測データをすべて削除します。よろしいですか？')) return;
    setUserPreds([]);
    await clearAll(uid);
  };

  // 合言葉を設定（複数端末同期を有効化）
  const handleSetPass = async (pass) => {
    const p = (pass || '').trim();
    if (!p) return;
    const h = await hashPassphrase(p);
    setStoredPass(p);
    setUid(h);
    setPassReady(true);
    await reloadUserPreds(h);
  };

  // 合言葉を解除（この端末をログアウト）
  const handleLogout = () => {
    clearStoredPass();
    setUid('');
    setPassReady(false);
    setStatusMsg('');
  };

  if (error) return <div className="glass-card" style={{ padding: '1.5rem' }}>データ取得エラー: {error}</div>;
  if (!info) return <div className="glass-card" style={{ padding: '1.5rem' }}>Loading...</div>;

  const selected = selectedRid ? info.races.find(r => r.race_id === selectedRid) : null;
  const selectedUserPred = selectedRid ? userPreds.find(p => p.race_id === selectedRid) : null;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ margin: 0 }}>予測対戦</h2>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
            対象日: {info.date} ({info.races.length} レース)
          </div>
        </div>
        <button
          onClick={handleClearAll}
          title="予測データ初期化"
          style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.4rem 0.6rem', background: 'transparent', border: '1px solid var(--border, #374151)', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.8rem' }}
        >
          <Trash2 size={14} /> 全削除
        </button>
      </div>

      <PassphraseBar
        passReady={passReady}
        statusMsg={statusMsg}
        onSetPass={handleSetPass}
        onLogout={handleLogout}
      />

      <HistorySummary settled={settled} />

      {selected ? (
        <RaceDetail
          race={selected}
          userPred={selectedUserPred}
          onSave={handleSavePred}
          onBack={() => setSelectedRid(null)}
        />
      ) : (
        <>
          {/* 今日のレース / 過去成績 の切替 */}
          <div className="tab-container" style={{ marginBottom: '1rem' }}>
            <button className={`tab-button ${view === 'today' ? 'active' : ''}`} onClick={() => setView('today')}>
              今日のレース（{info.races.length}）
            </button>
            <button className={`tab-button ${view === 'past' ? 'active' : ''}`} onClick={() => setView('past')}>
              過去成績・グラフ
            </button>
          </div>

          {view === 'today' ? (
            <RaceList races={info.races} userPreds={userPreds} onSelect={setSelectedRid} />
          ) : (
            <>
              <HitRateTrend settled={settled} />
              <PastRaces settled={settled} />
            </>
          )}
        </>
      )}
    </div>
  );
};

export default Battle;
