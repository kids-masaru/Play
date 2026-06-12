// ============================================================
// toto予測対戦：ユーザー予測(H/D/A)の保存先を抽象化するモジュール
// ------------------------------------------------------------
// 設計は battleStore.js（ボート）と同方針。合言葉(uid)はボートと共用
// （battleStore の hashPassphrase / getStoredPass 等をそのまま使う）。
// 保存パスだけ分離する:  users/{uid}/toto/{match_id}
//   match_id = "<回号>-<試合番号>"（例: "1635-1"）
//
// - Firebase 未設定: localStorage のみ（単一端末）
// - Firebase 設定 + 合言葉あり: Firestore に保存（複数端末で共有）
// ============================================================
import { firebaseConfig, isFirebaseConfigured } from './firebaseConfig';

const LOCAL_KEY = 'toto_predictions_v1';
const COLLECTION = 'toto';

let _db = null;
let _fs = null;

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
export async function loadTotoPreds(uid) {
  const db = await getDb();
  if (!db || !uid) return loadLocal();
  try {
    const snap = await _fs.getDocs(_fs.collection(db, 'users', uid, COLLECTION));
    const arr = snap.docs.map((d) => d.data());
    saveLocal(arr);
    return arr;
  } catch (e) {
    console.warn('[totoStore] cloud load 失敗、ローカルにフォールバック', e);
    return loadLocal();
  }
}

// 1件保存（ローカル即時 + クラウド裏書き）。pred.match_id をキーにする
export async function saveTotoPred(uid, pred) {
  const arr = loadLocal().filter((p) => p.match_id !== pred.match_id);
  arr.push(pred);
  saveLocal(arr);
  const db = await getDb();
  if (db && uid) {
    try {
      await _fs.setDoc(_fs.doc(db, 'users', uid, COLLECTION, String(pred.match_id)), pred);
    } catch (e) {
      console.warn('[totoStore] cloud save 失敗（ローカルには保存済み）', e);
    }
  }
  return arr;
}

// 全削除（ローカル + クラウド）
export async function clearTotoAll(uid) {
  saveLocal([]);
  const db = await getDb();
  if (db && uid) {
    try {
      const snap = await _fs.getDocs(_fs.collection(db, 'users', uid, COLLECTION));
      await Promise.all(snap.docs.map((d) => _fs.deleteDoc(d.ref)));
    } catch (e) {
      console.warn('[totoStore] cloud clear 失敗', e);
    }
  }
}

// ローカルにあってクラウドに無い予測をアップロード（合言葉設定時の初回移行）
export async function migrateTotoLocalToCloud(uid) {
  const db = await getDb();
  if (!db || !uid) return 0;
  const local = loadLocal();
  if (!local.length) return 0;
  try {
    const snap = await _fs.getDocs(_fs.collection(db, 'users', uid, COLLECTION));
    const cloudIds = new Set(snap.docs.map((d) => d.id));
    const toUpload = local.filter((p) => !cloudIds.has(String(p.match_id)));
    await Promise.all(
      toUpload.map((p) =>
        _fs.setDoc(_fs.doc(db, 'users', uid, COLLECTION, String(p.match_id)), p)
      )
    );
    return toUpload.length;
  } catch (e) {
    console.warn('[totoStore] migrate 失敗', e);
    return 0;
  }
}
