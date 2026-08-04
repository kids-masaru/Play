import React, { useEffect, useState } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell,
  LineChart, Line,
} from 'recharts';
import { Trophy, Target, Brain, Trash2, Cloud, CloudOff, KeyRound, LogOut, Clock, BarChart3 } from 'lucide-react';
// 合言葉(uid)はボート予測対戦と共用するため battleStore のものを流用
import {
  cloudEnabled, hashPassphrase,
  getStoredPass, setStoredPass, clearStoredPass,
} from './battleStore';
// 保存先は toto 専用（users/{uid}/toto/{match_id}）
import {
  loadTotoPreds, saveTotoPred, clearTotoAll, migrateTotoLocalToCloud,
} from './totoStore';

// 1X2 の表示ラベルと色
const PICK_META = {
  H: { label: 'ホーム勝', color: '#60a5fa' },
  D: { label: '引分', color: '#f59e0b' },
  A: { label: 'アウェイ勝', color: '#10b981' },
};
const PICKS = ['H', 'D', 'A'];

/** 締切までの残りをざっくり文字列化 */
const deadlineText = (deadline) => {
  if (!deadline) return '';
  const dl = new Date(deadline.replace(' ', 'T'));
  if (isNaN(dl)) return deadline;
  const diffMs = dl - new Date();
  if (diffMs <= 0) return '締切終了';
  const h = Math.floor(diffMs / 3600000);
  const d = Math.floor(h / 24);
  if (d >= 1) return `あと約${d}日`;
  return `あと約${h}時間`;
};

/** AI予想バッジ（統計 / Gemini / Codex） */
const AiPickBadge = ({ label, color, pick, sub }) => (
  <div style={{ padding: '0.4rem 0.6rem', background: `${color}12`, border: `1px solid ${color}33`, borderRadius: '6px', minWidth: '92px' }}>
    <div style={{ fontSize: '0.72rem', color, fontWeight: 600, marginBottom: '0.15rem' }}>{label}</div>
    {pick ? (
      <div style={{ fontSize: '0.9rem', fontWeight: 700 }}>
        {PICK_META[pick]?.label || pick}
        {sub && <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary, #9ca3af)', marginLeft: '0.3rem' }}>{sub}</span>}
      </div>
    ) : (
      <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)' }}>—</div>
    )}
  </div>
);

/** 的中マーク（結果が出ているときだけ表示） */
const HitMark = ({ pick, result }) => {
  if (!result || !pick) return null;
  const ok = pick === result;
  return (
    <span style={{ marginLeft: '0.3rem', fontSize: '0.75rem', fontWeight: 700, color: ok ? '#10b981' : '#ef4444' }}>
      {ok ? '✓' : '✗'}
    </span>
  );
};

/** 1試合カード */
const MatchCard = ({ match, userPred, onPick }) => {
  const [geminiOpen, setGeminiOpen] = useState(false);
  const [codexOpen, setCodexOpen] = useState(false);
  const stats = match.stats;
  // 統計モデルの確率（あれば）
  const statSub = stats
    ? `H${Math.round(stats.p_H * 100)}/D${Math.round(stats.p_D * 100)}/A${Math.round(stats.p_A * 100)}`
    : null;
  const userPick = userPred?.pick || '';
  const result = match.result || '';  // 確定結果 H/D/A（未確定は空）

  return (
    <div className="glass-card" style={{ padding: '1rem', marginBottom: '0.85rem', borderLeft: userPick ? '3px solid var(--accent-purple, #8b5cf6)' : '3px solid transparent' }}>
      {/* 対戦カード */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: '0.4rem' }}>
        <div style={{ fontSize: '1.05rem', fontWeight: 700 }}>
          <span style={{ color: '#60a5fa' }}>{match.home}</span>
          <span style={{ margin: '0 0.5rem', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.85rem' }}>vs</span>
          <span style={{ color: '#10b981' }}>{match.away}</span>
        </div>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)' }}>
          試合{match.no} / {match.date} {match.kickoff}
        </div>
      </div>

      {/* 確定結果（答え合わせ済みのとき） */}
      {result && (
        <div style={{ marginTop: '0.5rem', padding: '0.4rem 0.6rem', background: 'rgba(16,185,129,0.10)', border: '1px solid rgba(16,185,129,0.3)', borderRadius: '6px', fontSize: '0.85rem', fontWeight: 700 }}>
          結果: {PICK_META[result]?.label || result}
        </div>
      )}

      {/* AI予想 */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.65rem', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <AiPickBadge label="統計モデル" color="#60a5fa" pick={stats?.pick} sub={statSub} />
          <HitMark pick={stats?.pick} result={result} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <AiPickBadge label="Gemini" color="#a78bfa" pick={match.gemini_pick} sub={match.gemini_confidence ? `自信${match.gemini_confidence}` : null} />
          <HitMark pick={match.gemini_pick} result={result} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <AiPickBadge label="Codex" color="#f97316" pick={match.codex_pick} sub={match.codex_confidence ? `自信${match.codex_confidence}` : null} />
          <HitMark pick={match.codex_pick} result={result} />
        </div>
      </div>

      {/* Gemini推論（開閉） */}
      {match.gemini_reasoning && (
        <details open={geminiOpen} onToggle={(e) => setGeminiOpen(e.currentTarget.open)} style={{ marginTop: '0.6rem' }}>
          <summary style={{ cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600, color: '#a78bfa', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <Brain size={14} /> Geminiの推論を{geminiOpen ? '閉じる' : '読む'}
          </summary>
          <div style={{ marginTop: '0.4rem', whiteSpace: 'pre-wrap', fontSize: '0.83rem', lineHeight: 1.7, color: 'var(--text-primary, #f3f4f6)' }}>
            {match.gemini_reasoning}
          </div>
        </details>
      )}

      {/* Codex推論（開閉） */}
      {match.codex_reasoning && (
        <details open={codexOpen} onToggle={(e) => setCodexOpen(e.currentTarget.open)} style={{ marginTop: '0.55rem' }}>
          <summary style={{ cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600, color: '#f97316', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <Brain size={14} /> Codexの推論を{codexOpen ? '閉じる' : '読む'}
          </summary>
          <div style={{ marginTop: '0.4rem', whiteSpace: 'pre-wrap', fontSize: '0.83rem', lineHeight: 1.7, color: 'var(--text-primary, #f3f4f6)' }}>
            {match.codex_reasoning}
          </div>
        </details>
      )}

      {/* あなたの予想（H/D/A） */}
      <div style={{ marginTop: '0.75rem' }}>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.35rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          <Target size={14} /> あなたの予想
          {result && userPick && (
            <span style={{ fontWeight: 700, color: userPick === result ? '#10b981' : '#ef4444' }}>
              {userPick === result ? '　的中 ✓' : '　はずれ ✗'}
            </span>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
          {PICKS.map((p) => {
            const active = userPick === p;
            const isAnswer = result && p === result;  // 正解
            const meta = PICK_META[p];
            return (
              <button
                key={p}
                onClick={() => onPick(match, p)}
                disabled={!!result}
                style={{
                  padding: '0.55rem 0.3rem', borderRadius: '8px', cursor: result ? 'default' : 'pointer',
                  fontWeight: 700, fontSize: '0.9rem',
                  border: isAnswer ? '2px solid #10b981' : active ? `2px solid ${meta.color}` : '1px solid var(--border, #374151)',
                  background: isAnswer ? 'rgba(16,185,129,0.18)' : active ? `${meta.color}22` : 'rgba(255,255,255,0.03)',
                  color: isAnswer ? '#10b981' : active ? meta.color : 'var(--text-primary, #f3f4f6)',
                  opacity: result && !active && !isAnswer ? 0.5 : 1,
                  transition: 'all 0.12s',
                }}
              >
                <div style={{ fontSize: '1rem' }}>{p}{active && '●'}</div>
                <div style={{ fontSize: '0.7rem', fontWeight: 500 }}>{meta.label}</div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
};

/** 合言葉バー（ボートと共用の合言葉でクラウド同期） */
const PassphraseBar = ({ passReady, statusMsg, onSetPass, onLogout }) => {
  const [val, setVal] = useState('');
  if (!cloudEnabled()) {
    return (
      <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)' }}>
        <CloudOff size={15} /> この端末にのみ保存中（クラウド未設定）
      </div>
    );
  }
  if (!passReady) {
    return (
      <div className="glass-card" style={{ padding: '0.85rem 1rem', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.4rem' }}>
          <KeyRound size={16} /> 合言葉でクラウド同期（ボート予測対戦と共通）
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.5rem' }}>
          合言葉を入れると複数端末で予想を共有できます。
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="password" value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') onSetPass(val); }}
            placeholder="合言葉"
            style={{ flex: 1, padding: '0.5rem', background: 'rgba(0,0,0,0.3)', color: 'inherit', border: '1px solid var(--border, #374151)', borderRadius: '6px' }}
          />
          <button onClick={() => onSetPass(val)} style={{ padding: '0.5rem 1rem', background: 'var(--accent-purple, #8b5cf6)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}>設定</button>
        </div>
      </div>
    );
  }
  return (
    <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem' }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', color: 'var(--success, #10b981)' }}>
        <Cloud size={15} /> {statusMsg || 'クラウド同期中'}
      </span>
      <button onClick={onLogout} title="この端末で合言葉を解除" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.35rem 0.6rem', background: 'transparent', border: '1px solid var(--border, #374151)', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.78rem' }}>
        <LogOut size={13} /> 解除
      </button>
    </div>
  );
};

const Metric = ({ label, value, color }) => (
  <div style={{ textAlign: 'center' }}>
    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>{label}</div>
    <div style={{ fontSize: '1.6rem', fontWeight: 700, color }}>{value}</div>
  </div>
);

const rate = (hits, n) => (n > 0 ? `${Math.round((hits / n) * 100)}%` : '—');

/** 進捗・一致率・的中率サマリ */
const ProgressSummary = ({ matches, userByMid }) => {
  const total = matches.length;
  const done = matches.filter((m) => userByMid[m.match_id]?.pick).length;

  // あなた vs AI の一致（両方予想あり）
  let both = 0, agree = 0, codexBoth = 0, codexAgree = 0;
  // 結果が出た試合での的中数
  let settledN = 0;
  let uN = 0, uH = 0, gN = 0, gH = 0, cN = 0, cH = 0, sN = 0, sH = 0;
  matches.forEach((m) => {
    const up = userByMid[m.match_id]?.pick;
    if (up && m.gemini_pick) { both += 1; if (up === m.gemini_pick) agree += 1; }
    if (up && m.codex_pick) { codexBoth += 1; if (up === m.codex_pick) codexAgree += 1; }
    if (m.result) {
      settledN += 1;
      if (up) { uN += 1; if (up === m.result) uH += 1; }
      if (m.gemini_pick) { gN += 1; if (m.gemini_pick === m.result) gH += 1; }
      if (m.codex_pick) { cN += 1; if (m.codex_pick === m.result) cH += 1; }
      if (m.stats?.pick) { sN += 1; if (m.stats.pick === m.result) sH += 1; }
    }
  });
  const agreeRate = both > 0 ? `${Math.round((agree / both) * 100)}%` : '—';
  const codexAgreeRate = codexBoth > 0 ? `${Math.round((codexAgree / codexBoth) * 100)}%` : '—';

  return (
    <div className="glass-card" style={{ padding: '1rem 1.25rem', marginBottom: '1.25rem' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '0.85rem' }}>
        <Metric label="予想入力" value={`${done}/${total}`} color="var(--accent-purple, #a78bfa)" />
        <Metric label="Geminiと一致" value={agreeRate} color="#10b981" />
        <Metric label="Codexと一致" value={codexAgreeRate} color="#f97316" />
        {settledN > 0 && <>
          <Metric label={`あなた的中(${uH}/${uN})`} value={rate(uH, uN)} color="#8b5cf6" />
          <Metric label={`Gemini的中(${gH}/${gN})`} value={rate(gH, gN)} color="#a78bfa" />
          <Metric label={`Codex的中(${cH}/${cN})`} value={rate(cH, cN)} color="#f97316" />
          <Metric label={`統計的中(${sH}/${sN})`} value={rate(sH, sN)} color="#60a5fa" />
        </>}
      </div>
      {settledN > 0 && (
        <div style={{ marginTop: '0.6rem', fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)' }}>
          ※ {settledN}試合の結果が確定。あなた・Gemini・Codex・統計モデルの的中率を比較中。
        </div>
      )}
    </div>
  );
};

const SERIES = { stat: '#60a5fa', gemini: '#a78bfa', codex: '#f97316', user: '#ec4899' };

/** グラフ群: 予想の傾向 + 的中率比較 */
const TotoCharts = ({ matches, userByMid }) => {
  // 予想分布: 各予測者が H/D/A をそれぞれ何試合選んだか
  const dist = [
    { name: 'ホーム勝(H)', key: 'H' },
    { name: '引分(D)', key: 'D' },
    { name: 'アウェイ勝(A)', key: 'A' },
  ].map((row) => {
    let stat = 0, gemini = 0, codex = 0, user = 0;
    matches.forEach((m) => {
      if (m.stats?.pick === row.key) stat += 1;
      if (m.gemini_pick === row.key) gemini += 1;
      if (m.codex_pick === row.key) codex += 1;
      if (userByMid[m.match_id]?.pick === row.key) user += 1;
    });
    return { name: row.name, 統計: stat, Gemini: gemini, Codex: codex, あなた: user };
  });

  // 的中率: 結果が出た試合のみ
  let uN = 0, uH = 0, gN = 0, gH = 0, cN = 0, cH = 0, sN = 0, sH = 0;
  matches.forEach((m) => {
    if (!m.result) return;
    const up = userByMid[m.match_id]?.pick;
    if (up) { uN += 1; if (up === m.result) uH += 1; }
    if (m.gemini_pick) { gN += 1; if (m.gemini_pick === m.result) gH += 1; }
    if (m.codex_pick) { cN += 1; if (m.codex_pick === m.result) cH += 1; }
    if (m.stats?.pick) { sN += 1; if (m.stats.pick === m.result) sH += 1; }
  });
  const hasResult = (uN + gN + cN + sN) > 0;
  const acc = [
    { name: '統計', 的中率: sN ? Math.round((sH / sN) * 100) : 0, color: SERIES.stat },
    { name: 'Gemini', 的中率: gN ? Math.round((gH / gN) * 100) : 0, color: SERIES.gemini },
    { name: 'Codex', 的中率: cN ? Math.round((cH / cN) * 100) : 0, color: SERIES.codex },
    { name: 'あなた', 的中率: uN ? Math.round((uH / uN) * 100) : 0, color: SERIES.user },
  ];

  const axis = { stroke: 'var(--text-secondary, #9ca3af)', fontSize: 12, tickLine: false, axisLine: false };
  const tip = { backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: '0.8rem' };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem', marginBottom: '1.25rem' }}>
      {/* 予想の傾向 */}
      <div className="glass-card" style={{ padding: '1rem 1.1rem' }}>
        <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <BarChart3 size={17} /> 予想の傾向（{matches.length}試合）
        </h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={dist} barGap={2}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
            <XAxis dataKey="name" {...axis} />
            <YAxis {...axis} allowDecimals={false} />
            <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} contentStyle={tip} />
            <Legend wrapperStyle={{ fontSize: '0.78rem' }} />
            <Bar dataKey="統計" fill={SERIES.stat} radius={[3, 3, 0, 0]} />
            <Bar dataKey="Gemini" fill={SERIES.gemini} radius={[3, 3, 0, 0]} />
            <Bar dataKey="Codex" fill={SERIES.codex} radius={[3, 3, 0, 0]} />
            <Bar dataKey="あなた" fill={SERIES.user} radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* 的中率比較 */}
      <div className="glass-card" style={{ padding: '1rem 1.1rem' }}>
        <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
          <Trophy size={17} /> 的中率比較
        </h3>
        {hasResult ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={acc}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
              <XAxis dataKey="name" {...axis} />
              <YAxis {...axis} unit="%" domain={[0, 100]} />
              <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} contentStyle={tip} formatter={(v) => [`${v}%`, '的中率']} />
              <Bar dataKey="的中率" radius={[4, 4, 0, 0]}>
                {acc.map((e, i) => <Cell key={i} fill={e.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.85rem', lineHeight: 1.7 }}>
            試合結果が出ると、<br />統計・Gemini・Codex・あなたの的中率を<br />ここで比較します。
          </div>
        )}
      </div>
    </div>
  );
};

/** 円の符号付き表記 */
const yen = (v) => `${v >= 0 ? '+' : '-'}¥${Math.abs(Math.round(v)).toLocaleString()}`;

/** 等級別当せん金テーブル（toto公式の確定結果：1等〜の当せん金・口数） */
const PayoutTable = ({ detail, kujiLabel }) => {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const th = { padding: '0.5rem 0.7rem', textAlign: 'right', fontSize: '0.74rem', color: 'var(--text-secondary, #9ca3af)', fontWeight: 600, whiteSpace: 'nowrap', borderBottom: '1px solid rgba(255,255,255,0.12)' };
  const td = { padding: '0.55rem 0.7rem', textAlign: 'right', fontSize: '0.92rem', whiteSpace: 'nowrap', borderBottom: '1px solid rgba(255,255,255,0.06)' };
  return (
    <div className="glass-card" style={{ padding: '1rem 1.25rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Trophy size={17} /> 当せん金（{kujiLabel}・公式確定結果）
      </h3>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.6rem' }}>
        toto公式の等級別当せん金（1口=100円あたり）と当せん口数です。
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              <th style={{ ...th, textAlign: 'left' }}>等級</th>
              <th style={th}>当せん金</th>
              <th style={th}>当せん口数</th>
            </tr>
          </thead>
          <tbody>
            {detail.map((d) => (
              <tr key={d.rank}>
                <td style={{ ...td, textAlign: 'left', fontWeight: 700 }}>{d.rank}等</td>
                <td style={{ ...td, color: d.amount > 0 ? '#10b981' : '#f59e0b', fontWeight: 700 }}>
                  {d.amount > 0 ? `¥${d.amount.toLocaleString()}` : 'キャリーオーバー'}
                </td>
                <td style={{ ...td, color: 'var(--text-primary, #f3f4f6)' }}>
                  {d.count != null ? `${d.count.toLocaleString()}口` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

/** 当せん判定: そのくじ(toto/mini)を全問正解＝当せんしたか、予測者ごとに表示 */
const KujiVerdict = ({ kujiLabel, matches, userByMid, payout }) => {
  const total = matches.length;
  const settledN = matches.filter((m) => m.result).length;
  if (total === 0 || settledN === 0) return null;  // 結果がまだ1つも無ければ出さない
  const allSettled = settledN === total;

  const evalP = (getPick) => {
    let picked = 0, settledPicked = 0, hits = 0, missed = 0;
    matches.forEach((m) => {
      const p = getPick(m);
      if (!p) return;
      picked += 1;
      if (m.result) { settledPicked += 1; if (p === m.result) hits += 1; else missed += 1; }
    });
    return { picked, settledPicked, hits, missed, predictedAll: picked === total };
  };

  const rows = [
    { name: 'あなた', color: SERIES.user, e: evalP((m) => userByMid[m.match_id]?.pick) },
    { name: 'Gemini', color: SERIES.gemini, e: evalP((m) => m.gemini_pick) },
    { name: 'Codex', color: SERIES.codex, e: evalP((m) => m.codex_pick) },
    { name: '統計', color: SERIES.stat, e: evalP((m) => m.stats?.pick) },
  ];

  const verdictOf = (e) => {
    if (e.picked === 0) return { txt: '予想なし', color: 'var(--text-secondary, #6b7280)' };
    if (e.missed > 0) return { txt: `はずれ（${e.hits}/${e.settledPicked}的中）`, color: '#ef4444' };
    if (allSettled && e.predictedAll) return { txt: `当せん🎉（全${total}問的中）`, color: '#10b981' };
    if (allSettled && !e.predictedAll) return { txt: `対象外（${e.picked}/${total}試合しか予想なし）`, color: 'var(--text-secondary, #9ca3af)' };
    return { txt: `まだ可能性あり（${e.hits}/${settledN}的中・残り${total - settledN}試合）`, color: '#f59e0b' };
  };

  return (
    <div className="glass-card" style={{ padding: '1rem 1.25rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Trophy size={17} /> 当せん判定（{kujiLabel}・{allSettled ? `全${total}問確定` : `確定${settledN}/${total}問`}）
      </h3>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.6rem' }}>
        {total}問すべて正解で当せん。1問でも外すとその時点で終了です。
        {payout != null && (
          <span style={{ marginLeft: '0.4rem', color: payout > 0 ? '#10b981' : 'var(--text-secondary, #9ca3af)', fontWeight: 600 }}>
            ／ この回の1等当せん金: {payout > 0 ? `¥${payout.toLocaleString()}（1口100円あたり）` : '該当者なし（キャリーオーバー）'}
          </span>
        )}
      </div>
      {rows.map((r) => {
        const v = verdictOf(r.e);
        return (
          <div key={r.name} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.45rem 0', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <span style={{ color: r.color, fontWeight: 600 }}>{r.name}</span>
            <span style={{ color: v.color, fontWeight: 700, fontSize: '0.9rem' }}>{v.txt}</span>
          </div>
        );
      })}
    </div>
  );
};

/** 収支シミュレーション: 各回1口(100円)買い、全問的中なら1等当せん金が返る想定で投資/払戻/ROI */
const MoneySummary = ({ rounds, kuji, kujiLabel, userByMid }) => {
  // 全試合が確定した回だけ対象（勝敗・当せん金が確定するため）
  const done = rounds.filter((r) => r.kuji === kuji && r.matches.length > 0 && r.matches.every((m) => m.result));
  if (done.length === 0) return null;

  const calc = (getPick) => {
    let inv = 0, ret = 0, tickets = 0, wins = 0;
    done.forEach((r) => {
      const pickedAll = r.matches.every((m) => !!getPick(m));
      if (!pickedAll) return;           // 全試合の予想がそろって初めて1枚の券
      tickets += 1; inv += 100;
      if (r.matches.every((m) => getPick(m) === m.result)) { wins += 1; ret += (r.payout || 0); }
    });
    return { inv, ret, tickets, wins, profit: ret - inv, roi: inv > 0 ? Math.round((ret / inv) * 100) : null };
  };

  const cards = [
    { name: 'あなた', color: SERIES.user, m: calc((mm) => userByMid[mm.match_id]?.pick) },
    { name: 'Gemini', color: SERIES.gemini, m: calc((mm) => mm.gemini_pick) },
    { name: 'Codex', color: SERIES.codex, m: calc((mm) => mm.codex_pick) },
    { name: '統計', color: SERIES.stat, m: calc((mm) => mm.stats?.pick) },
  ];

  return (
    <div className="glass-card" style={{ padding: '1rem 1.25rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Trophy size={17} /> 収支シミュレーション（{kujiLabel}・1口100円換算）
      </h3>
      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.6rem' }}>
        各回1口(100円)買い、全問的中なら1等当せん金が返る想定。全試合確定した{done.length}回が対象。totoは還元率約50%＝基本は負け越し。
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: '0.5rem' }}>
        {cards.map((c) => (
          <div key={c.name} style={{ padding: '0.6rem 0.4rem', background: 'rgba(255,255,255,0.03)', border: `1px solid ${c.color}40`, borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '0.76rem', color: c.color, fontWeight: 600, marginBottom: '0.25rem' }}>{c.name}</div>
            {c.m.tickets > 0 ? (
              <>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: c.m.profit >= 0 ? '#10b981' : '#ef4444' }}>{yen(c.m.profit)}</div>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.2rem' }}>
                  ROI {c.m.roi ?? '-'}%<br />{c.m.wins}当せん<br />投資¥{c.m.inv.toLocaleString()}
                </div>
              </>
            ) : (
              <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary, #9ca3af)' }}>購入なし</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
};

/** 累積収支の推移（時系列・線グラフ）。1口100円・全問的中で当せん金。基本は右肩下がり。 */
const BalanceTrendToto = ({ rounds, kuji, kujiLabel, userByMid }) => {
  const done = rounds
    .filter((r) => r.kuji === kuji && r.matches.length > 0 && r.matches.every((m) => m.result))
    .sort((a, b) => a.round - b.round);  // 古い回→新しい回
  if (done.length === 0) return null;

  const step = (r, getPick) => {
    const pickedAll = r.matches.every((m) => !!getPick(m));
    if (!pickedAll) return null;  // 買っていない回は加算しない
    const won = r.matches.every((m) => getPick(m) === m.result);
    return (won ? (r.payout || 0) : 0) - 100;  // 払戻−投資(100円)
  };
  const getters = {
    あなた: (m) => userByMid[m.match_id]?.pick,
    Gemini: (m) => m.gemini_pick,
    Codex: (m) => m.codex_pick,
    統計: (m) => (m.stats ? m.stats.pick : ''),
  };
  // 1回でも券を買った系列だけ描画（統計は国際試合で買えず=非表示にする）
  const active = Object.keys(getters).filter((k) => done.some((r) => r.matches.every((m) => !!getters[k](m))));
  if (active.length === 0) return null;

  const cum = { あなた: 0, Gemini: 0, Codex: 0, 統計: 0 };
  const data = done.map((r) => {
    const row = { name: `第${r.round}回` };
    active.forEach((k) => {
      const s = step(r, getters[k]);
      if (s !== null) cum[k] += s;
      row[k] = Math.round(cum[k]);
    });
    return row;
  });

  const axis = { stroke: 'var(--text-secondary, #9ca3af)', fontSize: 12, tickLine: false, axisLine: false };
  const tip = { backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: '0.8rem' };
  const colorOf = { あなた: SERIES.user, Gemini: SERIES.gemini, Codex: SERIES.codex, 統計: SERIES.stat };
  return (
    <div className="glass-card" style={{ padding: '1rem 1.1rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <Trophy size={17} /> 累積収支の推移（{kujiLabel}・1口100円換算）
      </h3>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.6rem' }}>
        毎回1口買い続けたら今いくらか。当せんしなければ各回−100円ずつ。基本は右肩下がり。
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
          <XAxis dataKey="name" {...axis} />
          <YAxis {...axis} tickFormatter={(v) => `¥${v.toLocaleString()}`} width={64} />
          <Tooltip contentStyle={tip} formatter={(v) => [`¥${Number(v).toLocaleString()}`, '']} />
          <Legend wrapperStyle={{ fontSize: '0.78rem' }} />
          {active.map((k) => (
            <Line key={k} dataKey={k} stroke={colorOf[k]} dot={{ r: 3 }} strokeWidth={2.2} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

/** 回ごとの的中率の経緯（同じくじ種別の複数回を線グラフで） */
const RoundTrend = ({ rounds, userByMid, kuji, kujiLabel }) => {
  const data = [...rounds]
    .filter((r) => r.settled && r.kuji === kuji)
    .sort((a, b) => a.round - b.round)  // 古い回→新しい回
    .map((r) => {
      const sm = r.summary || {};
      const g = sm.gemini || { n: 0, hits: 0 };
      const c = sm.codex || { n: 0, hits: 0 };
      const s = sm.stat || { n: 0, hits: 0 };
      let uN = 0, uH = 0;
      r.matches.forEach((m) => {
        if (!m.result) return;
        const up = userByMid[m.match_id]?.pick;
        if (up) { uN += 1; if (up === m.result) uH += 1; }
      });
      return {
        name: `第${r.round}回`,
        統計: s.n ? Math.round((s.hits / s.n) * 100) : null,
        Gemini: g.n ? Math.round((g.hits / g.n) * 100) : null,
        Codex: c.n ? Math.round((c.hits / c.n) * 100) : null,
        あなた: uN ? Math.round((uH / uN) * 100) : null,
      };
    });
  if (data.length === 0) return null;

  const axis = { stroke: 'var(--text-secondary, #9ca3af)', fontSize: 12, tickLine: false, axisLine: false };
  const tip = { backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px', fontSize: '0.8rem' };
  return (
    <div className="glass-card" style={{ padding: '1rem 1.1rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <BarChart3 size={17} /> 回ごとの的中率の経緯（{kujiLabel} / 答え合わせ済み {data.length} 回）
      </h3>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.6rem' }}>
        各回の的中率(%)を統計・Gemini・Codex・あなたで比較。※統計モデルはJリーグ対戦のみ（国際試合は空）。
      </div>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={data} margin={{ top: 5, right: 10, bottom: 0, left: -10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" vertical={false} />
          <XAxis dataKey="name" {...axis} />
          <YAxis {...axis} unit="%" domain={[0, 100]} />
          <Tooltip contentStyle={tip} formatter={(v) => v == null ? ['-', ''] : [`${v}%`, '']} />
          <Legend wrapperStyle={{ fontSize: '0.78rem' }} />
          <Line dataKey="統計" stroke={SERIES.stat} connectNulls dot={{ r: 3 }} strokeWidth={2} />
          <Line dataKey="Gemini" stroke={SERIES.gemini} connectNulls dot={{ r: 3 }} strokeWidth={2} />
          <Line dataKey="Codex" stroke={SERIES.codex} connectNulls dot={{ r: 3 }} strokeWidth={2} />
          <Line dataKey="あなた" stroke={SERIES.user} connectNulls dot={{ r: 3 }} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

// くじ種別の短縮表示
const KUJI_SHORT = { toto: 'toto', mini_a: 'mini-A', mini_b: 'mini-B' };

/**
 * 全回まとめ表：プルダウンで切り替えなくても、結果が出た全ての回×くじ種別を
 * 一覧で比較できる。各セルは「的中数/確定数 (％)」。当せん（全問確定で全問的中）と
 * 配当金も併記する。
 */
const RoundsTable = ({ rounds, userByMid }) => {
  // 結果が1つでも出ている回だけを対象（新しい回→古い回、同回内は toto→A→B）
  const order = { toto: 0, mini_a: 1, mini_b: 2 };
  const rows = [...rounds]
    .filter((r) => r.matches.some((m) => m.result))
    .sort((a, b) => (b.round - a.round) || ((order[a.kuji] ?? 9) - (order[b.kuji] ?? 9)));
  if (rows.length === 0) return null;

  // ある予測者について、確定試合での的中数などを集計
  const evalP = (matches, getPick) => {
    let picked = 0, hits = 0, settledPicked = 0;
    matches.forEach((m) => {
      const p = getPick(m);
      if (!p) return;
      picked += 1;
      if (m.result) { settledPicked += 1; if (p === m.result) hits += 1; }
    });
    return { picked, hits, settledPicked };
  };
  // セル表示「的中/確定 (％)」
  const cell = (e) =>
    e.settledPicked > 0 ? `${e.hits}/${e.settledPicked} (${Math.round((e.hits / e.settledPicked) * 100)}%)` : '—';
  // その予測者が当せんしたか（全試合確定 & 全問予想 & 全問的中）
  const isWin = (total, settledN, e) => settledN === total && e.picked === total && e.hits === total;

  const th = { padding: '0.5rem 0.6rem', textAlign: 'center', fontSize: '0.74rem', color: 'var(--text-secondary, #9ca3af)', fontWeight: 600, whiteSpace: 'nowrap', borderBottom: '1px solid rgba(255,255,255,0.12)' };
  const td = { padding: '0.5rem 0.6rem', textAlign: 'center', fontSize: '0.82rem', whiteSpace: 'nowrap', borderBottom: '1px solid rgba(255,255,255,0.06)' };

  // 配当表示
  const payoutText = (p) => {
    if (p == null) return <span style={{ color: 'var(--text-secondary, #6b7280)' }}>未取得</span>;
    if (p === 0) return <span style={{ color: '#f59e0b' }}>CO</span>; // キャリーオーバー
    return <span style={{ color: '#10b981', fontWeight: 600 }}>¥{p.toLocaleString()}</span>;
  };

  // 的中セル（当せんなら🎉を付ける）
  const HitCell = ({ total, settledN, e, color }) => {
    const win = isWin(total, settledN, e);
    return (
      <td style={{ ...td, color: e.settledPicked > 0 ? color : 'var(--text-secondary, #6b7280)', fontWeight: win ? 700 : 500 }}>
        {cell(e)}{win && ' 🎉'}
      </td>
    );
  };

  return (
    <div className="glass-card" style={{ padding: '1rem 1.1rem', marginBottom: '1.25rem' }}>
      <h3 style={{ margin: '0 0 0.25rem 0', fontSize: '1rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
        <BarChart3 size={17} /> 全回まとめ（結果が出た {rows.length} 件）
      </h3>
      <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.6rem' }}>
        各セルは「的中数 / 確定した試合数（％）」。🎉＝そのくじを全問的中＝当せん。プルダウンで切替えなくても全回を一覧できます。
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: '520px' }}>
          <thead>
            <tr>
              <th style={{ ...th, textAlign: 'left' }}>回</th>
              <th style={{ ...th, textAlign: 'left' }}>くじ</th>
              <th style={th}>確定</th>
              <th style={{ ...th, color: SERIES.stat }}>統計</th>
              <th style={{ ...th, color: SERIES.gemini }}>Gemini</th>
              <th style={{ ...th, color: SERIES.codex }}>Codex</th>
              <th style={{ ...th, color: SERIES.user }}>あなた</th>
              <th style={th}>1等配当</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const total = r.matches.length;
              const settledN = r.matches.filter((m) => m.result).length;
              const eS = evalP(r.matches, (m) => m.stats?.pick);
              const eG = evalP(r.matches, (m) => m.gemini_pick);
              const eC = evalP(r.matches, (m) => m.codex_pick);
              const eU = evalP(r.matches, (m) => userByMid[m.match_id]?.pick);
              return (
                <tr key={`${r.round}-${r.kuji}`}>
                  <td style={{ ...td, textAlign: 'left', fontWeight: 600 }}>第{r.round}回</td>
                  <td style={{ ...td, textAlign: 'left' }}>{KUJI_SHORT[r.kuji] || r.kuji}</td>
                  <td style={{ ...td, color: settledN === total ? '#10b981' : '#f59e0b' }}>{settledN}/{total}</td>
                  <HitCell total={total} settledN={settledN} e={eS} color={SERIES.stat} />
                  <HitCell total={total} settledN={settledN} e={eG} color={SERIES.gemini} />
                  <HitCell total={total} settledN={settledN} e={eC} color={SERIES.codex} />
                  <HitCell total={total} settledN={settledN} e={eU} color={SERIES.user} />
                  <td style={td}>{payoutText(r.payout)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary, #6b7280)', marginTop: '0.5rem', lineHeight: 1.6 }}>
        ※「確定 3/5」＝5試合中3つだけ結果が出ている状態。全試合が確定して全問的中して初めて当せん（🎉）。<br />
        ※ 1等配当：CO＝該当者なしでキャリーオーバー、未取得＝結果がまだ公式反映前。
      </div>
    </div>
  );
};

const Toto = () => {
  const [roundsData, setRoundsData] = useState(null);   // { default_round, default_key, rounds:[...] }
  const [selectedKey, setSelectedKey] = useState(null); // `${round}-${kuji}`
  const [error, setError] = useState(null);
  const [userPreds, setUserPreds] = useState([]);
  const [uid, setUid] = useState('');
  const [passReady, setPassReady] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

  // 選択中のビュー（回×くじ種別）。toto_rounds.json から選ぶ
  const info = (roundsData && selectedKey)
    ? (roundsData.rounds.find((r) => `${r.round}-${r.kuji}` === selectedKey) || roundsData.rounds[0])
    : null;

  const reloadUserPreds = async (theUid) => {
    if (cloudEnabled() && theUid) {
      const moved = await migrateTotoLocalToCloud(theUid);
      const arr = await loadTotoPreds(theUid);
      setUserPreds(arr);
      setStatusMsg(moved > 0 ? `クラウド同期中（${moved}件を移行）` : 'クラウド同期中');
    } else {
      const arr = await loadTotoPreds(null);
      setUserPreds(arr);
      setStatusMsg('');
    }
  };

  // 初回: 保存済み合言葉の復元 + データ取得
  useEffect(() => {
    const saved = getStoredPass();
    if (cloudEnabled() && saved) {
      hashPassphrase(saved).then((h) => {
        setUid(h);
        setPassReady(true);
        reloadUserPreds(h);
      });
    } else {
      // effect 直下での同期 state 更新を避け、保存先の読み込み完了後に反映する。
      loadTotoPreds(null).then((arr) => {
        setUserPreds(arr);
        setStatusMsg('');
      });
    }
    // 日次更新データの古いキャッシュを避けるためクエリで打ち消す
    const cb = `?t=${Date.now()}`;
    // 全回データ（過去の答え合わせも回切替で閲覧）。無ければ単一回にフォールバック。
    fetch(`./daily_data/toto_rounds.json${cb}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(`HTTP ${res.status}`)))
      .then((d) => { setRoundsData(d); setSelectedKey(d.default_key || `${d.default_round}-toto`); })
      .catch(() => {
        fetch(`./daily_data/toto_info.json${cb}`)
          .then((res) => (res.ok ? res.json() : Promise.reject(`HTTP ${res.status}`)))
          .then((one) => {
            const kuji = one.kuji || 'toto';
            setRoundsData({ default_round: one.round, default_key: `${one.round}-${kuji}`, rounds: [{ ...one, kuji, kuji_label: one.kuji_label || 'toto' }] });
            setSelectedKey(`${one.round}-${kuji}`);
          })
          .catch((err) => setError(String(err)));
      });
  }, []);

  const handlePick = (match, pick) => {
    const newPred = {
      match_id: match.match_id,
      round: info.round,
      no: match.no,
      home: match.home,
      away: match.away,
      date: match.date,
      pick,
      timestamp: new Date().toISOString(),
    };
    // 楽観更新 → 永続化
    const updated = userPreds.filter((p) => p.match_id !== newPred.match_id);
    updated.push(newPred);
    setUserPreds(updated);
    saveTotoPred(uid, newPred);
  };

  const handleClearAll = async () => {
    if (!confirm('toto の予想データをすべて削除します。よろしいですか？')) return;
    setUserPreds([]);
    await clearTotoAll(uid);
  };

  const handleSetPass = async (pass) => {
    const p = (pass || '').trim();
    if (!p) return;
    const h = await hashPassphrase(p);
    setStoredPass(p);
    setUid(h);
    setPassReady(true);
    await reloadUserPreds(h);
  };

  const handleLogout = () => {
    clearStoredPass();
    setUid('');
    setPassReady(false);
    setStatusMsg('');
  };

  if (error) return <div className="glass-card" style={{ padding: '1.5rem' }}>toto データ取得エラー: {error}<div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.5rem' }}>※ toto_rounds.json / toto_info.json が未生成の可能性。`python toto/generate_toto_data.py` を実行してください。</div></div>;
  if (!info) return <div className="glass-card" style={{ padding: '1.5rem' }}>Loading...</div>;

  const userByMid = Object.fromEntries(userPreds.map((p) => [p.match_id, p]));

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <h2 style={{ margin: 0 }}>toto 予測対戦 / 第{info.round}回 <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary, #9ca3af)' }}>{info.kuji_label || ''}</span></h2>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)', display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.2rem' }}>
            <Clock size={14} /> 投票締切 {info.deadline}（{deadlineText(info.deadline)}）・{info.matches.length}試合
          </div>
        </div>
        <button onClick={handleClearAll} title="予想データ初期化" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.4rem 0.6rem', background: 'transparent', border: '1px solid var(--border, #374151)', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.8rem' }}>
          <Trash2 size={14} /> 全削除
        </button>
      </div>

      {/* 回・くじ種別の切替（過去の答え合わせ / mini toto も見られる） */}
      {roundsData.rounds.length > 1 && (
        <div style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.82rem', color: 'var(--text-secondary, #9ca3af)' }}>回・種別を選ぶ:</span>
          <select
            value={selectedKey || ''}
            onChange={(e) => setSelectedKey(e.target.value)}
            style={{ padding: '0.4rem 0.6rem', background: 'rgba(0,0,0,0.3)', color: 'inherit', border: '1px solid var(--border, #374151)', borderRadius: '6px', fontSize: '0.85rem' }}
          >
            {roundsData.rounds.map((r) => {
              const sm = r.summary;
              const tag = r.settled
                ? `結果あり${sm && sm.gemini && sm.gemini.n ? ` (Gemini ${sm.gemini.hits}/${sm.gemini.n})` : ''}${sm && sm.codex && sm.codex.n ? ` (Codex ${sm.codex.hits}/${sm.codex.n})` : ''}`
                : (deadlineText(r.deadline) || '');
              const key = `${r.round}-${r.kuji}`;
              return <option key={key} value={key}>第{r.round}回 {r.kuji_label || r.kuji}{tag ? ` / ${tag}` : ''}</option>;
            })}
          </select>
          {selectedKey === (roundsData.default_key || `${roundsData.default_round}-toto`) && (
            <span style={{ fontSize: '0.75rem', color: 'var(--accent-purple, #a78bfa)' }}>← 最新</span>
          )}
        </div>
      )}

      {!info.has_gemini && (
        <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)' }}>
          ※ この回はまだ AI(Gemini) 予想が未生成です。
        </div>
      )}
      {!info.has_codex && (
        <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)' }}>
          ※ この回はまだ AI(Codex) 予想が未生成です。次回の週次更新から自動で作成されます。
        </div>
      )}

      <PassphraseBar passReady={passReady} statusMsg={statusMsg} onSetPass={handleSetPass} onLogout={handleLogout} />

      {/* 全回まとめ表（プルダウン不要で全回を一覧比較） */}
      <RoundsTable rounds={roundsData.rounds} userByMid={userByMid} />

      <KujiVerdict kujiLabel={info.kuji_label || info.kuji} matches={info.matches} userByMid={userByMid} payout={info.payout} />

      <PayoutTable detail={info.payout_detail} kujiLabel={info.kuji_label || info.kuji} />

      <MoneySummary rounds={roundsData.rounds} kuji={info.kuji} kujiLabel={info.kuji_label || info.kuji} userByMid={userByMid} />

      <BalanceTrendToto rounds={roundsData.rounds} kuji={info.kuji} kujiLabel={info.kuji_label || info.kuji} userByMid={userByMid} />

      <ProgressSummary matches={info.matches} userByMid={userByMid} />

      <RoundTrend rounds={roundsData.rounds} userByMid={userByMid} kuji={info.kuji} kujiLabel={info.kuji_label || info.kuji} />

      <TotoCharts matches={info.matches} userByMid={userByMid} />

      {info.matches.map((m) => (
        <MatchCard key={m.match_id} match={m} userPred={userByMid[m.match_id]} onPick={handlePick} />
      ))}

      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '1rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
        <Trophy size={13} /> 結果が出た回は上の「回を選ぶ」で切替えて答え合わせ（あなた・Gemini・Codex・統計）を確認できます。
      </div>
    </div>
  );
};

export default Toto;
