"""
verify_calibration.py - 確率較正のA/Bテスト

時系列を 3分割:
  - model_train: 最古〜(max-60d)
  - calib:       (max-60d)〜(max-30d)  ← 較正器fit用
  - val:         (max-30d)〜max         ← ROI評価用

3モデル(1st/2nd/3rd) を model_train で学習 → calib で予測 → 較正器 fit
val で 較正なし/あり の両方で realistic_evaluator を回してROI比較。
"""
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auto_research.calibration import MultiClassCalibrator
from auto_research import realistic_evaluator as RE

FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
RESULTS_FILE = os.path.join(ROOT, "past_data", "past_history_results.csv")
ODDS_FILE = os.path.join(ROOT, "past_data", "past_odds_3t.csv")
CALIB_FILE = os.path.join(ROOT, "models", "calibrators.pkl")

VAL_DAYS = 180
CALIB_DAYS = 60        # val の直前 60 日を較正に
RANDOM_STATE = 42

LGB_PARAMS = {
    "objective": "multiclass", "num_class": 6, "metric": "multi_error",
    "boosting_type": "gbdt", "learning_rate": 0.05, "num_leaves": 31,
    "verbose": -1, "seed": RANDOM_STATE,
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

    max_date = df["Date"].max()
    val_start = max_date - timedelta(days=VAL_DAYS)
    calib_start = val_start - timedelta(days=CALIB_DAYS)

    model_train_df = df[df["Date"] < calib_start].copy()
    calib_df       = df[(df["Date"] >= calib_start) & (df["Date"] < val_start)].copy()
    val_df         = df[df["Date"] >= val_start].copy()

    feat_cols = [c for c in df.columns if c not in EXCLUDE_COLS and df[c].dtype in ["int64", "float64"]]
    return model_train_df, calib_df, val_df, feat_cols


def train_model(train_df, feat_cols, target_col):
    X = train_df[feat_cols]
    y = train_df[target_col].astype(int) - 1
    X_tr, X_va, y_tr, y_va = train_test_split(X, y, test_size=0.1, random_state=RANDOM_STATE)
    dtr = lgb.Dataset(X_tr, label=y_tr)
    dva = lgb.Dataset(X_va, label=y_va, reference=dtr)
    return lgb.train(
        LGB_PARAMS, dtr, num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[dva],
        callbacks=[lgb.early_stopping(EARLY_STOPPING), lgb.log_evaluation(0)],
    )


class CalibratedModel:
    """LGB Booster + MultiClassCalibrator のラッパー。.predict だけ提供"""
    def __init__(self, model, cal):
        self.model = model
        self.cal = cal

    def predict(self, X):
        raw = self.model.predict(X)
        return self.cal.transform(raw)


def main():
    print("=" * 60)
    print(" 確率較正 A/B テスト")
    print("=" * 60)

    print("\n[1/5] データ分割...")
    model_train_df, calib_df, val_df, feat_cols = load_and_split()
    print(f"  model_train: {len(model_train_df)} 件 ({model_train_df['Date'].min().date()} ~ {model_train_df['Date'].max().date()})")
    print(f"  calib:       {len(calib_df)} 件 ({calib_df['Date'].min().date() if len(calib_df) else '-'} ~ {calib_df['Date'].max().date() if len(calib_df) else '-'})")
    print(f"  val:         {len(val_df)} 件 ({val_df['Date'].min().date()} ~ {val_df['Date'].max().date()})")
    print(f"  features:    {len(feat_cols)}")

    if len(calib_df) < 100:
        print("[ERROR] calib期間のデータが少なすぎます")
        return 1

    print("\n[2/5] 3モデル学習 (model_train で)...")
    m1 = train_model(model_train_df, feat_cols, "Target_1st")
    m2 = train_model(model_train_df, feat_cols, "Target_2nd")
    m3 = train_model(model_train_df, feat_cols, "Target_3rd")

    print("\n[3/5] calib期間で生確率取得 → 較正器 fit...")
    Xc = calib_df[feat_cols]
    raw_1 = m1.predict(Xc)
    raw_2 = m2.predict(Xc)
    raw_3 = m3.predict(Xc)
    y1 = (calib_df["Target_1st"].astype(int) - 1).values
    y2 = (calib_df["Target_2nd"].astype(int) - 1).values
    y3 = (calib_df["Target_3rd"].astype(int) - 1).values

    cal1 = MultiClassCalibrator(6).fit(raw_1, y1)
    cal2 = MultiClassCalibrator(6).fit(raw_2, y2)
    cal3 = MultiClassCalibrator(6).fit(raw_3, y3)

    # 較正前後の比較メトリクス（calib期間で）
    def class_brier(p, y):
        # クラス yに対する Brier スコア (低いほど良い)
        return np.mean((p[np.arange(len(y)), y] - 1.0) ** 2 + np.sum(p ** 2, axis=1) - p[np.arange(len(y)), y] ** 2)

    for name, raw, cal_obj, y in [("1st", raw_1, cal1, y1), ("2nd", raw_2, cal2, y2), ("3rd", raw_3, cal3, y3)]:
        cal = cal_obj.transform(raw)
        b_raw = class_brier(raw, y)
        b_cal = class_brier(cal, y)
        print(f"  [{name}] Brier 生={b_raw:.4f} 較正後={b_cal:.4f} 改善={b_raw-b_cal:+.4f}")

    print("\n[4/5] 結果・オッズ読み込み...")
    results_df = pd.read_csv(RESULTS_FILE)
    odds_df = pd.read_csv(ODDS_FILE)
    odds_race_ids = set(odds_df["ID"].astype(str).unique())
    val_with_odds = val_df[val_df["ID"].astype(str).isin(odds_race_ids)].copy()
    print(f"  val ∩ odds: {len(val_with_odds)} レース")

    print("\n[5/5] val期間で realistic_evaluator を 較正なし/あり で実行...")

    # --- 較正なし ---
    buys_raw = RE.simulate_realistic_buys(val_with_odds, feat_cols, m1, m2, m3, odds_df)
    metrics_raw = RE.evaluate_buys(buys_raw, results_df)

    # --- 較正あり ---
    cm1 = CalibratedModel(m1, cal1)
    cm2 = CalibratedModel(m2, cal2)
    cm3 = CalibratedModel(m3, cal3)
    buys_cal = RE.simulate_realistic_buys(val_with_odds, feat_cols, cm1, cm2, cm3, odds_df)
    metrics_cal = RE.evaluate_buys(buys_cal, results_df)

    # --- 比較 ---
    print("\n" + "=" * 60)
    print(" 結果比較")
    print("=" * 60)
    fmt = "{:<25} {:>15} {:>15}"
    print(fmt.format("指標", "較正なし", "較正あり"))
    print("-" * 60)
    print(fmt.format("ROI %", f"{metrics_raw['roi']:.2f}", f"{metrics_cal['roi']:.2f}"))
    print(fmt.format("的中率 %", f"{metrics_raw['hit_rate']:.2f}", f"{metrics_cal['hit_rate']:.2f}"))
    print(fmt.format("取引回数", str(metrics_raw['n_trades']), str(metrics_cal['n_trades'])))
    print(fmt.format("的中数", str(metrics_raw['n_hits']), str(metrics_cal['n_hits'])))
    print(fmt.format("投資額(円)", f"{metrics_raw['invest']:,}", f"{metrics_cal['invest']:,}"))
    print(fmt.format("回収額(円)", f"{metrics_raw['return']:,}", f"{metrics_cal['return']:,}"))
    print(fmt.format("損益(円)", f"{metrics_raw['return']-metrics_raw['invest']:,}",
                                  f"{metrics_cal['return']-metrics_cal['invest']:,}"))

    print(f"\n実運用 (4/1〜4/26): ROI 37.4%")
    print(f"較正なし との差: {abs(metrics_raw['roi'] - 37.4):.1f} pt")
    print(f"較正あり との差: {abs(metrics_cal['roi'] - 37.4):.1f} pt")

    # 較正器を保存
    print(f"\n較正器を保存: {CALIB_FILE}")
    import pickle
    with open(CALIB_FILE, "wb") as f:
        pickle.dump({"1st": cal1, "2nd": cal2, "3rd": cal3}, f)

    return 0


if __name__ == "__main__":
    sys.exit(main())
