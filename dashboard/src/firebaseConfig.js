// ============================================================
// Firebase 設定値
// ------------------------------------------------------------
// Firebase コンソール > プロジェクトの設定 > マイアプリ(ウェブ) で
// 表示される firebaseConfig をここに貼り付ける。
//
// ※ これらの値は「秘密情報」ではない（公開して安全）。
//    本当の保護は Firestore セキュリティルール + 合言葉(uid) で行う。
//
// ※ 下記がプレースホルダ("PASTE_...")のままの間は、自動的に
//    従来のブラウザ内保存(localStorage)で動作する（＝壊れない）。
// ============================================================
export const firebaseConfig = {
  apiKey: "AIzaSyCZRMmZfzdOJRqNW1l0ocrw5vVWlas-7pg",
  authDomain: "boatrace-battle.firebaseapp.com",
  projectId: "boatrace-battle",
  storageBucket: "boatrace-battle.firebasestorage.app",
  messagingSenderId: "1026928954293",
  appId: "1:1026928954293:web:e3783bfb17de0f546e67fc",
};

// 設定済みか判定（プレースホルダのままなら未設定扱い）
export const isFirebaseConfigured = () =>
  Boolean(firebaseConfig.apiKey) && !firebaseConfig.apiKey.startsWith("PASTE_");
