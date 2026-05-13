"""
verify_realistic.py - 新評価器(realistic_evaluator)を過去データで実行し、
現行 evaluator と比較。実運用ROI(~37%)に近い数値が出るか検証する。

使用法:
    python auto_research/verify_realistic.py
"""
import os
import sys
from datetime import timedelta

import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import train_test_split

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auto_research import realistic_evaluator as RE
from auto_research import evaluator as OLD


FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
RESULTS_FILE = os.path.join(ROOT, "past_data", "past_history_results.csv")
ODDS_FILE = os.path.join(ROOT, "past_data", "past_odds_3t.csv")

VAL_DAYS = 30
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

EXCLUDE_COLS = [
    "ID", "Date", "Venue", "Weather", "WindDir", "Result", "Payout",
    "Target_1st", "Target_2nd", "Target_3rd",
]


def load_and_split():
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
    X = train_df[feature_cols]
    y = train_df[target_col].astype(int) - 1
    X_tr, X_va, y_tr, y_va = train_test_split(
        X, y, test_size=0.1, random_state=RANDOM_STATE
    )
    dtrain = lgb.Dataset(X_tr, label=y_tr)
    dvalid = lgb.Dataset(X_va, label=y_va, reference=dtrain)
    return lgb.train(
        LGB_PARAMS,
        dtrain,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[dvalid],
        callbacks=[
            lgb.early_stopping(stopping_rounds=EARLY_STOPPING),
            lgb.log_evaluation(0),
        ],
    )


def main():
    print("=" * 60)
    print(" 新評価器 vs 旧評価器 比較検証")
    print("=" * 60)

    print("\n[1/4] データ読み込み・分割...", flush=True)
    train_df, val_df, feature_cols = load_and_split()
    print(f"  train: {len(train_df)} 件 / val: {len(val_df)} 件 / 特徴量: {len(feature_cols)} 個")
    print(f"  val期間: {val_df['Date'].min().date()} ～ {val_df['Date'].max().date()}")

    print("\n[2/4] LightGBM 1st/2nd/3rd 学習...", flush=True)
    m1 = train_one(train_df, feature_cols, "Target_1st")
    m2 = train_one(train_df, feature_cols, "Target_2nd")
    m3 = train_one(train_df, feature_cols, "Target_3rd")

    print("\n[3/4] 結果・オッズ読み込み...", flush=True)
    results_df = pd.read_csv(RESULTS_FILE)
    odds_df = pd.read_csv(ODDS_FILE)
    print(f"  results: {len(results_df)} 件 / odds: {len(odds_df)} 件 ({odds_df['ID'].nunique()} レース)")

    # オッズが存在する val レースのみで評価する (両評価器とも同条件にする)
    odds_race_ids = set(odds_df['ID'].astype(str).unique())
    val_with_odds = val_df[val_df['ID'].astype(str).isin(odds_race_ids)].copy()
    print(f"  val ∩ odds: {len(val_with_odds)} レース")

    print("\n[4/4] 両評価器で買い目生成・評価...", flush=True)

    # ----- 旧評価器: top3確率を100円固定 -----
    from auto_research.experiment import simulate_buys as old_simulate, BUY_TOP_K, MIN_TOP_PROB
    old_buys = old_simulate(val_with_odds, feature_cols, m1, m2, m3)
    old_metrics = OLD.evaluate(old_buys, results_df, odds_df)

    # ----- 新評価器: EV+Kelly (本番準拠) -----
    new_buys = RE.simulate_realistic_buys(val_with_odds, feature_cols, m1, m2, m3, odds_df)
    new_metrics = RE.evaluate_buys(new_buys, results_df)

    # ----- 比較表示 -----
    print("\n" + "=" * 60)
    print(" 結果比較")
    print("=" * 60)

    fmt = "{:<25} {:>15} {:>15}"
    print(fmt.format("指標", "旧 (top3 100円)", "新 (EV+Kelly)"))
    print("-" * 60)
    print(fmt.format("ROI %", f"{old_metrics['roi']:.2f}", f"{new_metrics['roi']:.2f}"))
    print(fmt.format("的中率 %", f"{old_metrics['hit_rate']:.2f}", f"{new_metrics['hit_rate']:.2f}"))
    print(fmt.format("取引回数", str(old_metrics['n_trades']), str(new_metrics['n_trades'])))
    print(fmt.format("的中数", str(old_metrics['n_hits']), str(new_metrics['n_hits'])))
    print(fmt.format("投資額(円)", f"{old_metrics['invest']:,}", f"{new_metrics['invest']:,}"))
    print(fmt.format("回収額(円)", f"{old_metrics['return']:,}", f"{new_metrics['return']:,}"))
    print(fmt.format("損益(円)", f"{old_metrics['return']-old_metrics['invest']:,}",
                                 f"{new_metrics['return']-new_metrics['invest']:,}"))
    if 'n_races' in new_metrics:
        print(fmt.format("買ったレース数", "-", str(new_metrics['n_races'])))

    print("\n比較指標:")
    print(f"  実運用 (4/1〜4/26 dashboard): ROI 37.4% (143,800円投資→53,790円回収, -90,010円)")
    print(f"  新評価器との差: {abs(new_metrics['roi'] - 37.4):.1f} ポイント")

    # 買い目サンプル出力
    if not new_buys.empty:
        print(f"\n新評価器 買い目サンプル (先頭10件):")
        print(new_buys.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
