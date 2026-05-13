"""
retrain_post_leak_fix.py - リーク修正後の本番モデル再学習スクリプト（一回限り）

目的:
  build_features.py のリーク修正後、本番投入用 lgb_model_1st/2nd/3rd.txt を
  リーク無し ml_features.csv で再学習し、強制的に置き換える。

A/Bテストはしない理由:
  既存モデルはリーク有りデータで学習済み。リーク無しテストデータで評価すると
  特徴量の意味が変わっているので「旧の方が精度が高く見える」誤判定が起こりうる。
  ここは無条件に新モデルで上書きするのが正しい。
"""
import os
import sys
import shutil

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
MODEL_DIR = os.path.join(ROOT, "models")
RANDOM_STATE = 42

EXCLUDE_COLS = [
    "ID", "Date", "Venue", "Weather", "WindDir", "Result", "Payout",
    "Target_1st", "Target_2nd", "Target_3rd",
]

LGB_PARAMS = {
    "objective": "multiclass",
    "num_class": 6,
    "metric": "multi_error",
    "boosting_type": "gbdt",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "verbose": -1,
    "seed": RANDOM_STATE,
}
NUM_BOOST_ROUND = 200
EARLY_STOPPING = 20


def get_xy(df, target_col):
    df = df.dropna(subset=[target_col])
    feat_cols = [c for c in df.columns if c not in EXCLUDE_COLS and df[c].dtype in ["int64", "float64"]]
    X = df[feat_cols]
    y = df[target_col].astype(int) - 1
    return X, y, feat_cols


def train(df, target_col, label):
    X, y, feat_cols = get_xy(df, target_col)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE)
    dtrain = lgb.Dataset(X_tr, label=y_tr)
    dtest  = lgb.Dataset(X_te, label=y_te, reference=dtrain)

    print(f"[{label}] 学習開始 (train={len(X_tr)}, test={len(X_te)}, features={len(feat_cols)})")
    model = lgb.train(
        LGB_PARAMS, dtrain,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[dtest],
        callbacks=[lgb.early_stopping(EARLY_STOPPING), lgb.log_evaluation(0)],
    )
    y_pred = np.argmax(model.predict(X_te), axis=1)
    acc = accuracy_score(y_te, y_pred)
    print(f"[{label}] 新モデル test accuracy: {acc*100:.2f}%")
    return model, acc


def evaluate_old(model_file, df, target_col, label):
    if not os.path.exists(model_file):
        print(f"[{label}] 旧モデルが存在しないため比較スキップ")
        return None
    X, y, _ = get_xy(df, target_col)
    _, X_te, _, y_te = train_test_split(X, y, test_size=0.2, random_state=RANDOM_STATE)
    try:
        old = lgb.Booster(model_file=model_file)
        old_feats = old.feature_name()
        avail = [f for f in old_feats if f in X_te.columns]
        if len(avail) < len(old_feats):
            print(f"[{label}] [WARN] 旧モデルの特徴量 {len(old_feats)} 中 {len(avail)} 利用可")
        # 旧モデルが期待する全特徴量で評価できないと正しい評価にならないので、ここでは参考値
        if len(avail) != len(old_feats):
            print(f"[{label}] 旧モデル評価は参考値（特徴量不一致のためフェアではない）")
            return None
        y_pred = np.argmax(old.predict(X_te[avail]), axis=1)
        acc = accuracy_score(y_te, y_pred)
        print(f"[{label}] 旧モデル(リーク有り学習済み) test accuracy: {acc*100:.2f}% [参考]")
        return acc
    except Exception as e:
        print(f"[{label}] 旧モデル評価失敗: {e}")
        return None


def replace(model, model_path, label):
    """OneDrive配下にLightGBMが直接 save_model できないため、
    Windows tempに書いてから shutil.copy で OneDrive にコピーする。"""
    import tempfile
    backup = model_path.replace(".txt", "_pre_leak_fix.txt")
    if os.path.exists(model_path):
        if not os.path.exists(backup):
            shutil.copy2(model_path, backup)
            print(f"[{label}] バックアップ作成: {backup}")
        os.remove(model_path)
    # OS temp に書く (OneDrive を経由しない)
    tmp_dir = tempfile.gettempdir()
    tmp_path = os.path.join(tmp_dir, os.path.basename(model_path))
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    model.save_model(tmp_path)
    # その後コピーで OneDrive 配下に配置（Python I/O は大丈夫）
    shutil.copy2(tmp_path, model_path)
    os.remove(tmp_path)
    print(f"[{label}] 新モデルで上書き: {model_path}")


def main():
    print("=" * 60)
    print(" リーク修正後の本番モデル再学習")
    print("=" * 60)

    if not os.path.exists(FEATURES_FILE):
        print(f"[ERROR] {FEATURES_FILE} が見つかりません")
        return 1

    print(f"\n[1/2] {FEATURES_FILE} を読み込み中...")
    df = pd.read_csv(FEATURES_FILE)
    print(f"  shape: {df.shape}")

    targets = [
        ("Target_1st", os.path.join(MODEL_DIR, "lgb_model_1st.txt"), "1着予測"),
        ("Target_2nd", os.path.join(MODEL_DIR, "lgb_model_2nd.txt"), "2着予測"),
        ("Target_3rd", os.path.join(MODEL_DIR, "lgb_model_3rd.txt"), "3着予測"),
    ]

    print(f"\n[2/2] 3モデルを再学習・上書き")
    for tgt, mfile, label in targets:
        print(f"\n--- {label} ---")
        evaluate_old(mfile, df, tgt, label)
        new_model, new_acc = train(df, tgt, label)
        replace(new_model, mfile, label)

    print("\n" + "=" * 60)
    print(" 完了。本番モデルはリーク無しデータで再学習済み。")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
