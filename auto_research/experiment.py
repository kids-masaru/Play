"""
experiment.py - 自己改善ループの1試行実行スクリプト

処理の流れ:
1. build_features.py を呼んで ml_features.csv を再生成
2. 時系列分割（val = 最新30日）
3. LightGBM 1st/2nd/3rd を学習
4. val期間の各レースで3連単確率を推定し、Top-K買い目を決定
5. past_history_results.csv の実結果と比較し、ROI等を計算
6. auto_research/results.tsv に1行追記

使用法:
    python auto_research/experiment.py [--note "変更内容の短い説明"]
"""
import os
import sys
import argparse
import subprocess
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split

# このファイルからプロジェクトルートに遡る
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auto_research import evaluator  # noqa: E402

# --- 設定 ---
FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
RESULTS_FILE = os.path.join(ROOT, "past_data", "past_history_results.csv")
ODDS_FILE = os.path.join(ROOT, "past_data", "past_odds_3t.csv")
RESULTS_TSV = os.path.join(ROOT, "auto_research", "results.tsv")

VAL_DAYS = 30                  # 直近N日を検証期間に
BUY_TOP_K = 3                  # 1レースあたりの買い目数
MIN_TOP_PROB = 0.05            # top1確率がこれ未満のレースはスキップ
STAKE_PER_COMBO = 100          # 1買い目あたりの賭け金(円)
RANDOM_STATE = 42

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

# retrain_model.py と同じ除外カラム
EXCLUDE_COLS = [
    "ID", "Date", "Venue", "Weather", "WindDir", "Result", "Payout",
    "Target_1st", "Target_2nd", "Target_3rd",
]


def regenerate_features():
    """build_features.main() を呼び出して ml_features.csv を再生成する"""
    print("[1/5] 特徴量を再生成中...", flush=True)
    try:
        import build_features
        # build_features はキャッシュされている場合があるためリロード
        import importlib
        importlib.reload(build_features)
        build_features.main()
    except Exception as e:
        raise RuntimeError(f"build_features.main() が失敗: {e}")

    if not os.path.exists(FEATURES_FILE):
        raise FileNotFoundError(f"{FEATURES_FILE} が生成されませんでした")


def load_and_split():
    """ml_features.csv を読み込み、時系列分割する"""
    df = pd.read_csv(FEATURES_FILE)
    df = df.dropna(subset=["Target_1st", "Target_2nd", "Target_3rd"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    split_date = df["Date"].max() - timedelta(days=VAL_DAYS)
    train_df = df[df["Date"] < split_date].copy()
    val_df = df[df["Date"] >= split_date].copy()

    feature_cols = [
        c for c in df.columns
        if c not in EXCLUDE_COLS and df[c].dtype in ["int64", "float64"]
    ]
    return train_df, val_df, feature_cols


def train_one(train_df, feature_cols, target_col):
    """指定ターゲットで LightGBM を1つ学習し返す"""
    X = train_df[feature_cols]
    y = train_df[target_col].astype(int) - 1  # 1-6 → 0-5

    X_tr, X_va, y_tr, y_va = train_test_split(
        X, y, test_size=0.1, random_state=RANDOM_STATE
    )
    dtrain = lgb.Dataset(X_tr, label=y_tr)
    dvalid = lgb.Dataset(X_va, label=y_va, reference=dtrain)

    model = lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[dvalid],
        callbacks=[
            lgb.early_stopping(stopping_rounds=EARLY_STOPPING),
            lgb.log_evaluation(0),
        ],
    )
    return model


def estimate_trifecta_probs(p1, p2, p3, top_n=BUY_TOP_K):
    """3モデルの確率から3連単確率Top-Nを推定する（local_ai_pipeline.py と同じロジック）"""
    combos = []
    for i in range(6):
        pi = p1[i]
        if pi < 0.01:
            continue
        denom2 = max(1.0 - p2[i], 1e-10)
        for j in range(6):
            if j == i:
                continue
            pj = p2[j] / denom2
            denom3 = max(1.0 - p3[i] - p3[j], 1e-10)
            for k in range(6):
                if k == i or k == j:
                    continue
                pk = p3[k] / denom3
                prob = pi * pj * pk
                if prob > 0.0005:
                    combos.append((f"{i+1}-{j+1}-{k+1}", prob))
    combos.sort(key=lambda x: x[1], reverse=True)
    total = sum(p for _, p in combos)
    if total > 0:
        combos = [(c, p / total) for c, p in combos]
    return combos[:top_n]


def simulate_buys(val_df, feature_cols, m1, m2, m3):
    """val_df に対して各レースでTop-K買い目を生成する"""
    X = val_df[feature_cols]
    probs_1 = m1.predict(X)  # shape: (N, 6)
    probs_2 = m2.predict(X)
    probs_3 = m3.predict(X)

    buys = []
    for idx, (_, row) in enumerate(val_df.iterrows()):
        p1 = probs_1[idx]
        p2 = probs_2[idx]
        p3 = probs_3[idx]

        # top1確率が低すぎるレースはスキップ
        if max(p1) < MIN_TOP_PROB:
            continue

        combos = estimate_trifecta_probs(p1, p2, p3, top_n=BUY_TOP_K)
        for combo_str, _prob in combos:
            buys.append({
                "race_id": str(row["ID"]),
                "combo": combo_str,
                "stake": STAKE_PER_COMBO,
            })
    return pd.DataFrame(buys)


def get_git_hash():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def append_result(trial_id, git_hash, metrics, change_summary):
    """results.tsv に1行追記する。ファイルがなければヘッダ付きで作成"""
    header = [
        "trial_id", "timestamp", "git_hash",
        "roi", "hit_rate", "n_trades", "n_hits",
        "invest", "return", "composite_score",
        "change_summary", "is_kept",
    ]
    row = [
        str(trial_id),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        git_hash,
        f"{metrics['roi']:.2f}",
        f"{metrics['hit_rate']:.2f}",
        str(metrics["n_trades"]),
        str(metrics["n_hits"]),
        str(metrics["invest"]),
        str(metrics["return"]),
        f"{metrics['composite_score']:.2f}",
        change_summary.replace("\t", " ").replace("\n", " "),
        "0",  # is_kept は Claude Code 側で commit 時に更新する運用
    ]

    need_header = not os.path.exists(RESULTS_TSV)
    with open(RESULTS_TSV, "a", encoding="utf-8") as f:
        if need_header:
            f.write("\t".join(header) + "\n")
        f.write("\t".join(row) + "\n")


def get_next_trial_id():
    if not os.path.exists(RESULTS_TSV):
        return 1
    df = pd.read_csv(RESULTS_TSV, sep="\t")
    if df.empty:
        return 1
    return int(df["trial_id"].max()) + 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", type=str, default="(no note)",
                        help="build_features.py の変更内容を1行で")
    parser.add_argument("--skip-rebuild", action="store_true",
                        help="ml_features.csv を再生成せず既存を使う（デバッグ用）")
    args = parser.parse_args()

    start = datetime.now()
    os.chdir(ROOT)  # プロジェクトルートで動作

    # 1. 特徴量再生成
    if not args.skip_rebuild:
        regenerate_features()
    else:
        print("[1/5] 特徴量再生成をスキップ（既存 ml_features.csv を使用）")

    # 2. データ分割
    print("[2/5] データを時系列分割中...", flush=True)
    train_df, val_df, feature_cols = load_and_split()
    print(f"    train: {len(train_df)} 件 / val: {len(val_df)} 件 / 特徴量: {len(feature_cols)} 個")

    # 3. 3モデル学習
    print("[3/5] LightGBM 1st/2nd/3rd を学習中...", flush=True)
    m1 = train_one(train_df, feature_cols, "Target_1st")
    m2 = train_one(train_df, feature_cols, "Target_2nd")
    m3 = train_one(train_df, feature_cols, "Target_3rd")

    # 4. 買い目シミュレーション
    print("[4/5] val期間で買い目をシミュレーション中...", flush=True)
    buy_df = simulate_buys(val_df, feature_cols, m1, m2, m3)
    print(f"    買い目: {len(buy_df)} 件")

    # 5. 評価と記録
    print("[5/5] 指標を計算し results.tsv に追記...", flush=True)
    results_df = pd.read_csv(RESULTS_FILE)
    odds_df = pd.read_csv(ODDS_FILE) if os.path.exists(ODDS_FILE) else pd.DataFrame()
    metrics = evaluator.evaluate(buy_df, results_df, odds_df)

    trial_id = get_next_trial_id()
    git_hash = get_git_hash()
    append_result(trial_id, git_hash, metrics, args.note)

    elapsed = (datetime.now() - start).total_seconds()
    print("\n" + "=" * 60)
    print(f"Trial #{trial_id} 完了（{elapsed:.1f}秒）")
    print(f"  ROI            : {metrics['roi']:.2f}%")
    print(f"  的中率         : {metrics['hit_rate']:.2f}%")
    print(f"  取引回数       : {metrics['n_trades']}")
    print(f"  投資/回収      : {metrics['invest']} / {metrics['return']} 円")
    print(f"  複合スコア     : {metrics['composite_score']:.2f}")
    print(f"  git_hash       : {git_hash}")
    print(f"  記録先         : {RESULTS_TSV}")
    print("=" * 60)


if __name__ == "__main__":
    main()
