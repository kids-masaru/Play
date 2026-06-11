// ============================================================
// 予測対戦：ユーザー予測の保存先を抽象化するモジュール
// ------------------------------------------------------------
// - Firebase 未設定時: 従来どおり localStorage のみ（単一端末）
// - Firebase 設定時 + 合言葉あり: Firestore に保存（複数端末で共有）
//   localStorage はオフライン用キャッシュ兼フォールバックとして併用。
//
// 合言葉(passphrase)は SHA-256 でハッシュ化し、その値を Firestore 上の
// 自分専用フォルダID(uid)として使う:  users/{uid}/predictions/{race_id}
// → 合言葉を知らない人はこのパスを推測できないので、軽い保護になる。
// ============================================================
import { firebaseConfig, isFirebaseConfigured } from './firebaseConfig';

const LOCAL_KEY = 'battle_predictions_v1';  // 既存キー（互換のため踏襲）
const PASS_KEY = 'battle_pass_v1';

let _db = null;
let _fs = null;  // firestore 関数群（遅延 import）

// Firestore を遅延初期化。未設定なら null を返す（firebase を import すらしない）。
async function getDb() {
  if (_db) return _db;
  if (!isFirebaseConfigured()) return null;
  const { initializeApp } = await import('firebase/app');
  const fs = await import('firebase/firestore');
  const app = initializeApp(firebaseConfig);
  _db = fs.getFirestore(app);
  _fs = fs;
  return _db;
}

export const cloudEnabled = () => isFirebaseConfigured();

// --- 合言葉 ---
export async function hashPassphrase(pass) {
  const data = new TextEncoder().encode('battle:' + pass);
  const buf = await crypto.subtle.digest('SHA-256', data);
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
export const getStoredPass = () => localStorage.getItem(PASS_KEY) || '';
export const setStoredPass = (p) => localStorage.setItem(PASS_KEY, p);
export const clearStoredPass = () => localStorage.removeItem(PASS_KEY);

// --- localStorage（キャッシュ / フォールバック） ---
const loadLocal = () => {
  try {
    return JSON.parse(localStorage.getItem(LOCAL_KEY) || '[]');
  } catch {
    return [];
  }
};
const saveLocal = (arr) => localStorage.setItem(LOCAL_KEY, JSON.stringify(arr));

// 予測一覧をロード（クラウド優先、失敗時はローカル）
export async function loadPredictions(uid) {
  const db = await getDb();
  if (!db || !uid) return loadLocal();
  try {
    const snap = await _fs.getDocs(_fs.collection(db, 'users', uid, 'predictions'));
    const arr = snap.docs.map((d) => d.data());
    saveLocal(arr);  // キャッシュ更新
    return arr;
  } catch (e) {
    console.warn('[battleStore] cloud load 失敗、ローカルにフォールバック', e);
    return loadLocal();
  }
}

// 1件保存（ローカル即時 + クラウド裏書き）
export async function savePrediction(uid, pred) {
  const arr = loadLocal().filter((p) => p.race_id !== pred.race_id);
  arr.push(pred);
  saveLocal(arr);
  const db = await getDb();
  if (db && uid) {
    try {
      await _fs.setDoc(_fs.doc(db, 'users', uid, 'predictions', String(pred.race_id)), pred);
    } catch (e) {
      console.warn('[battleStore] cloud save 失敗（ローカルには保存済み）', e);
    }
  }
  return arr;
}

// 全削除（ローカル + クラウド）
export async function clearAll(uid) {
  saveLocal([]);
  const db = await getDb();
  if (db && uid) {
    try {
      const snap = await _fs.getDocs(_fs.collection(db, 'users', uid, 'predictions'));
      await Promise.all(snap.docs.map((d) => _fs.deleteDoc(d.ref)));
    } catch (e) {
      console.warn('[battleStore] cloud clear 失敗', e);
    }
  }
}

// ローカルにあってクラウドに無い予測をアップロード（合言葉設定時の初回移行）。戻り値=移行件数
export async function migrateLocalToCloud(uid) {
  const db = await getDb();
  if (!db || !uid) return 0;
  const local = loadLocal();
  if (!local.length) return 0;
  try {
    const snap = await _fs.getDocs(_fs.collection(db, 'users', uid, 'predictions'));
    const cloudIds = new Set(snap.docs.map((d) => d.id));
    const toUpload = local.filter((p) => !cloudIds.has(String(p.race_id)));
    await Promise.all(
      toUpload.map((p) =>
        _fs.setDoc(_fs.doc(db, 'users', uid, 'predictions', String(p.race_id)), p)
      )
    );
    return toUpload.length;
  } catch (e) {
    console.warn('[battleStore] migrate 失敗', e);
    return 0;
  }
}
