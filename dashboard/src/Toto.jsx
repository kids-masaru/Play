import React, { useEffect, useState } from 'react';
import { Trophy, Target, Brain, Trash2, Cloud, CloudOff, KeyRound, LogOut, Clock } from 'lucide-react';
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

/** AI予想バッジ（統計 or Gemini） */
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

/** 1試合カード */
const MatchCard = ({ match, userPred, onPick }) => {
  const [open, setOpen] = useState(false);
  const stats = match.stats;
  // 統計モデルの確率（あれば）
  const statSub = stats
    ? `H${Math.round(stats.p_H * 100)}/D${Math.round(stats.p_D * 100)}/A${Math.round(stats.p_A * 100)}`
    : null;
  const userPick = userPred?.pick || '';

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
          試合{match.no}　{match.date} {match.kickoff}
        </div>
      </div>

      {/* AI予想 */}
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.65rem' }}>
        <AiPickBadge label="統計モデル" color="#60a5fa" pick={stats?.pick} sub={statSub} />
        <AiPickBadge label="Gemini" color="#a78bfa" pick={match.gemini_pick} sub={match.gemini_confidence ? `自信${match.gemini_confidence}` : null} />
      </div>

      {/* Gemini推論（開閉） */}
      {match.gemini_reasoning && (
        <details open={open} onToggle={(e) => setOpen(e.currentTarget.open)} style={{ marginTop: '0.6rem' }}>
          <summary style={{ cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600, color: '#a78bfa', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
            <Brain size={14} /> Geminiの推論を{open ? '閉じる' : '読む'}
          </summary>
          <div style={{ marginTop: '0.4rem', whiteSpace: 'pre-wrap', fontSize: '0.83rem', lineHeight: 1.7, color: 'var(--text-primary, #f3f4f6)' }}>
            {match.gemini_reasoning}
          </div>
        </details>
      )}

      {/* あなたの予想（H/D/A） */}
      <div style={{ marginTop: '0.75rem' }}>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.35rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
          <Target size={14} /> あなたの予想
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.5rem' }}>
          {PICKS.map((p) => {
            const active = userPick === p;
            const meta = PICK_META[p];
            return (
              <button
                key={p}
                onClick={() => onPick(match, p)}
                style={{
                  padding: '0.55rem 0.3rem', borderRadius: '8px', cursor: 'pointer',
                  fontWeight: 700, fontSize: '0.9rem',
                  border: active ? `2px solid ${meta.color}` : '1px solid var(--border, #374151)',
                  background: active ? `${meta.color}22` : 'rgba(255,255,255,0.03)',
                  color: active ? meta.color : 'var(--text-primary, #f3f4f6)',
                  transition: 'all 0.12s',
                }}
              >
                <div style={{ fontSize: '1rem' }}>{p}</div>
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

/** 進捗・一致率サマリ（結果が出るまでの即時フィードバック） */
const ProgressSummary = ({ matches, userByMid }) => {
  const total = matches.length;
  const done = matches.filter((m) => userByMid[m.match_id]?.pick).length;
  // あなた vs Gemini の一致数（両方予想があるもの）
  let both = 0, agree = 0;
  matches.forEach((m) => {
    const up = userByMid[m.match_id]?.pick;
    if (up && m.gemini_pick) {
      both += 1;
      if (up === m.gemini_pick) agree += 1;
    }
  });
  const agreeRate = both > 0 ? Math.round((agree / both) * 100) : null;
  return (
    <div className="glass-card" style={{ padding: '1rem 1.25rem', marginBottom: '1.25rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.85rem' }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>予想入力</div>
        <div style={{ fontSize: '1.6rem', fontWeight: 700, color: 'var(--accent-purple, #a78bfa)' }}>{done}/{total}</div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary, #9ca3af)', marginBottom: '0.25rem' }}>Geminiと一致</div>
        <div style={{ fontSize: '1.6rem', fontWeight: 700, color: '#10b981' }}>{agreeRate === null ? '—' : `${agreeRate}%`}</div>
      </div>
    </div>
  );
};

const Toto = () => {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [userPreds, setUserPreds] = useState([]);
  const [uid, setUid] = useState('');
  const [passReady, setPassReady] = useState(false);
  const [statusMsg, setStatusMsg] = useState('');

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
      reloadUserPreds(null);
    }
    fetch('./daily_data/toto_info.json')
      .then((res) => (res.ok ? res.json() : Promise.reject(`HTTP ${res.status}`)))
      .then(setInfo)
      .catch((err) => setError(String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  if (error) return <div className="glass-card" style={{ padding: '1.5rem' }}>toto データ取得エラー: {error}<div style={{ fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '0.5rem' }}>※ toto_info.json が未生成の可能性。`python toto/generate_toto_data.py` を実行してください。</div></div>;
  if (!info) return <div className="glass-card" style={{ padding: '1.5rem' }}>Loading...</div>;

  const userByMid = Object.fromEntries(userPreds.map((p) => [p.match_id, p]));

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem', flexWrap: 'wrap', gap: '0.5rem' }}>
        <div>
          <h2 style={{ margin: 0 }}>toto 予測対戦　第{info.round}回</h2>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary, #9ca3af)', display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '0.2rem' }}>
            <Clock size={14} /> 投票締切 {info.deadline}（{deadlineText(info.deadline)}）・{info.matches.length}試合
          </div>
        </div>
        <button onClick={handleClearAll} title="予想データ初期化" style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.4rem 0.6rem', background: 'transparent', border: '1px solid var(--border, #374151)', borderRadius: '6px', cursor: 'pointer', color: 'var(--text-secondary, #9ca3af)', fontSize: '0.8rem' }}>
          <Trash2 size={14} /> 全削除
        </button>
      </div>

      {!info.has_gemini && (
        <div className="glass-card" style={{ padding: '0.6rem 0.9rem', marginBottom: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary, #9ca3af)' }}>
          ※ この回はまだ AI(Gemini) 予想が未生成です。
        </div>
      )}

      <PassphraseBar passReady={passReady} statusMsg={statusMsg} onSetPass={handleSetPass} onLogout={handleLogout} />

      <ProgressSummary matches={info.matches} userByMid={userByMid} />

      {info.matches.map((m) => (
        <MatchCard key={m.match_id} match={m} userPred={userByMid[m.match_id]} onPick={handlePick} />
      ))}

      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary, #9ca3af)', marginTop: '1rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
        <Trophy size={13} /> 試合結果が出たら、統計・Gemini・あなたの的中率を比較表示します（次の機能で対応予定）。
      </div>
    </div>
  );
};

export default Toto;
