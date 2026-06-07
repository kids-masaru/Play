import React, { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  LineChart, Line, Legend
} from 'recharts';
import { Trophy, Target, Brain, ChevronLeft, Save, Trash2 } from 'lucide-react';

const STORAGE_KEY = 'battle_predictions_v1';

/** ユーザー予測の localStorage 操作 */
const loadUserPredictions = () => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
};
const saveUserPredictions = (arr) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
};

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
        const aiPicks = parseAiPicks(race.ai_picks_det);
        const hasUser = !!userByRid[race.race_id];
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
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>
              <div>AI予測 (Det):</div>
              <div style={{ marginTop: '0.25rem', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                {aiPicks.length > 0
                  ? aiPicks.slice(0, 3).map((p, i) => (
                    <span key={i} style={{ marginRight: '0.5rem' }}>{p.combo}{p.stake ? `:${p.stake}` : ''}</span>
                  ))
                  : '(なし)'}
                {aiPicks.length > 3 && <span> ...</span>}
              </div>
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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>Det版 (本番)</div>
            <div style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
              {aiDet.length > 0
                ? aiDet.map((p, i) => <div key={i}>{p.combo}{p.stake ? `  ¥${p.stake}` : ''}</div>)
                : '(なし)'}
            </div>
          </div>
          <div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>LLM版 (参考)</div>
            <div style={{ fontFamily: 'monospace', fontSize: '0.9rem' }}>
              {aiLlm.length > 0
                ? aiLlm.map((p, i) => <div key={i}>{p.combo}{p.stake ? `  ¥${p.stake}` : ''}</div>)
                : '(なし)'}
            </div>
          </div>
        </div>
        {race.ai_log && (
          <details style={{ marginTop: '0.75rem' }}>
            <summary style={{ cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>AI推論ログ (展開)</summary>
            <pre style={{ marginTop: '0.5rem', whiteSpace: 'pre-wrap', fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)' }}>{race.ai_log}</pre>
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

/** 履歴サマリパネル (タブの上に表示) */
const HistorySummary = ({ userPreds, history }) => {
  // history: daily_history_results.csv をパースした結果 [{ID, Result, Payout}]
  const histByRid = Object.fromEntries(history.map(h => [h.ID, h]));
  const enriched = userPreds.map(p => {
    const h = histByRid[p.race_id];
    if (!h) return { ...p, result: null, hit: null, payout: 0 };
    const result = String(h.Result).replace(/\s/g, '');
    const hit = p.picks.some(combo => isHit(combo, result));
    return { ...p, result, hit, payout: hit ? Number(h.Payout) : 0 };
  }).filter(p => p.result !== null);

  const total = enriched.length;
  const hits = enriched.filter(p => p.hit).length;
  const hitRate = total > 0 ? (hits / total * 100).toFixed(1) : '-';

  // ユーザーROI (stake指定があるもののみ)
  const withStake = enriched.filter(p => p.stake);
  const invest = withStake.reduce((sum, p) => sum + p.stake * p.picks.length, 0);
  const ret = withStake.reduce((sum, p) => sum + (p.hit ? p.payout * (p.stake / 100) : 0), 0);
  const roi = invest > 0 ? (ret / invest * 100).toFixed(1) : '-';

  return (
    <div className="glass-card" style={{ padding: '1.25rem', marginBottom: '1.5rem' }}>
      <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Trophy size={18} /> あなたの戦績 (結果が出たレースのみ)
      </h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '1rem' }}>
        <Stat label="判定済レース" value={total} />
        <Stat label="的中" value={hits} />
        <Stat label="的中率" value={`${hitRate}%`} />
        <Stat label="ROI (想定額入力分)" value={`${roi}%`} accent />
      </div>
    </div>
  );
};

const Stat = ({ label, value, accent }) => (
  <div style={{ textAlign: 'center' }}>
    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>{label}</div>
    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: accent ? 'var(--accent-blue, #60a5fa)' : 'inherit' }}>{value}</div>
  </div>
);

/** トップレベルコンポーネント */
const Battle = () => {
  const [info, setInfo] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [selectedRid, setSelectedRid] = useState(null);
  const [userPreds, setUserPreds] = useState(loadUserPredictions());

  useEffect(() => {
    fetch('./daily_data/daily_race_info.json')
      .then(res => res.ok ? res.json() : Promise.reject(`HTTP ${res.status}`))
      .then(setInfo)
      .catch(err => setError(String(err)));

    // 履歴は CSV を簡易パース
    fetch('./daily_data/daily_history_results.csv')
      .then(res => res.ok ? res.text() : '')
      .then(text => {
        if (!text) return;
        const lines = text.split('\n').filter(l => l.trim());
        const headers = lines[0].split(',');
        const idxID = headers.indexOf('ID');
        const idxResult = headers.indexOf('Result');
        const idxPayout = headers.indexOf('Payout');
        const rows = lines.slice(1).map(l => {
          const cols = l.split(',');
          return {
            ID: cols[idxID],
            Result: cols[idxResult],
            Payout: cols[idxPayout],
          };
        });
        setHistory(rows);
      })
      .catch(() => {});
  }, []);

  const handleSavePred = (newPred) => {
    const updated = userPreds.filter(p => p.race_id !== newPred.race_id);
    updated.push(newPred);
    setUserPreds(updated);
    saveUserPredictions(updated);
  };

  const handleClearAll = () => {
    if (!confirm('あなたの予測データをすべて削除します。よろしいですか？')) return;
    setUserPreds([]);
    saveUserPredictions([]);
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

      <HistorySummary userPreds={userPreds} history={history} />

      {selected ? (
        <RaceDetail
          race={selected}
          userPred={selectedUserPred}
          onSave={handleSavePred}
          onBack={() => setSelectedRid(null)}
        />
      ) : (
        <RaceList races={info.races} userPreds={userPreds} onSelect={setSelectedRid} />
      )}
    </div>
  );
};

export default Battle;
