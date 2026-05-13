"""
walkforward_evaluator.py - walk-forward backtest 評価器 (ハイブリッド版)

(A) 2年WF: モデル精度評価 (Brier / log-loss / top-1/top-3 accuracy)
    - 期間: ml_features.csv 全体 (2024-01-01〜)、評価開始は2024-07以降
    - ウィンドウ: expanding window、月初再学習、評価は週単位
    - オッズ不要、過去全体で評価可能

(B) 45日WF: 実オッズROI評価
    - 期間: past_odds_3t.csv のある範囲 (2026-03-28〜)
    - ウィンドウ: expanding window、週ごとに再学習、評価は週単位
    - Det / LLM相当 の2モードで実オッズROIを算出

使用法:
    python auto_research/walkforward_evaluator.py --mode accuracy   # (A) のみ
    python auto_research/walkforward_evaluator.py --mode roi        # (B) のみ
    python auto_research/walkforward_evaluator.py --mode both       # 両方
"""

import os
import sys
import json
import argparse
import warnings
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore", category=UserWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auto_research import realistic_evaluator as RE  # noqa: E402

# --- 設定 ---
FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
RESULTS_FILE = os.path.join(ROOT, "past_data", "past_history_results.csv")
ODDS_FILE = os.path.join(ROOT, "past_data", "past_odds_3t.csv")

OUTPUT_DIR = os.path.join(ROOT, "auto_research")
MODEL_RESULTS_CSV = os.path.join(OUTPUT_DIR, "wf_model_results.csv")
ROI_RESULTS_CSV = os.path.join(OUTPUT_DIR, "wf_roi_results.csv")

# 2年WF (A) 設定
ACC_WARMUP_MONTHS = 6     # 学習データ確保のためのウォームアップ期間
ACC_RETRAIN_FREQ = "M"    # 月初再学習
# 45日WF (B) 設定
ROI_RETRAIN_FREQ = "W"    # 週ごと再学習
ROI_MIN_TRAIN_DAYS = 14   # 最低限の学習データ確保

# LightGBM 共通パラメータ
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

# Det フィルタ (現行 morning_odds_runner.py と同値)
DET_FILTERS = {"ev_thr": 2.0, "prob_min": 0.01, "odds_max": 500}
# LLM相当 フィルタ (deterministic 近似、フィルタなし)
LLM_FILTERS = {"ev_thr": 1.0, "prob_min": None, "odds_max": None}


# =========================================================
# 共通ユーティリティ
# =========================================================
def load_features():
    """ml_features.csv を読み込み、Date 順にソートして返す"""
    df = pd.read_csv(FEATURES_FILE)
    df = df.dropna(subset=["Target_1st", "Target_2nd", "Target_3rd"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    feature_cols = [
        c for c in df.columns
        if c not in EXCLUDE_COLS and df[c].dtype in ["int64", "float64"]
    ]
    return df, feature_cols


def train_three_models(train_df, feature_cols):
    """3モデル (1着/2着/3着) を学習して返す"""
    def _train_one(target_col):
        X = train_df[feature_cols]
        y = train_df[target_col].astype(int) - 1
        X_tr, X_va, y_tr, y_va = train_test_split(
            X, y, test_size=0.1, random_state=RANDOM_STATE
        )
        return lgb.train(
            LGB_PARAMS,
            lgb.Dataset(X_tr, label=y_tr),
            num_boost_round=NUM_BOOST_ROUND,
            valid_sets=[lgb.Dataset(X_va, label=y_va)],
            callbacks=[lgb.early_stopping(EARLY_STOPPING), lgb.log_evaluation(0)],
        )
    return _train_one("Target_1st"), _train_one("Target_2nd"), _train_one("Target_3rd")


def gen_week_blocks(start_date, end_date):
    """[start_date, end_date) の範囲を週単位のブロックに分割。
    各ブロックは (week_start, week_end) のタプル。week_end は含まない。"""
    blocks = []
    cur = start_date
    while cur < end_date:
        nxt = cur + timedelta(days=7)
        if nxt > end_date:
            nxt = end_date
        blocks.append((cur, nxt))
        cur = nxt
    return blocks


# =========================================================
# (A) 2年WF モデル精度評価
# =========================================================
def compute_accuracy_metrics(val_df, feature_cols, m1, m2, m3):
    """モデル精度指標を計算
    戻り値: dict (brier_1st, log_loss_1st, top1_1st, top3_1st, brier_2nd, brier_3rd, n_races)
    """
    if len(val_df) == 0:
        return None
    X = val_df[feature_cols]
    p1 = m1.predict(X)
    p2 = m2.predict(X)
    p3 = m3.predict(X)
    y1 = val_df["Target_1st"].astype(int).values - 1
    y2 = val_df["Target_2nd"].astype(int).values - 1
    y3 = val_df["Target_3rd"].astype(int).values - 1

    n = len(val_df)

    # one-hot 化
    def onehot(y, n_classes=6):
        oh = np.zeros((len(y), n_classes))
        oh[np.arange(len(y)), y] = 1
        return oh

    # Brier score (multi-class): mean over all samples and classes
    brier_1 = float(np.mean(np.sum((p1 - onehot(y1)) ** 2, axis=1)))
    brier_2 = float(np.mean(np.sum((p2 - onehot(y2)) ** 2, axis=1)))
    brier_3 = float(np.mean(np.sum((p3 - onehot(y3)) ** 2, axis=1)))

    # log-loss
    eps = 1e-15
    ll_1 = float(-np.mean(np.log(np.clip(p1[np.arange(n), y1], eps, 1))))
    ll_2 = float(-np.mean(np.log(np.clip(p2[np.arange(n), y2], eps, 1))))
    ll_3 = float(-np.mean(np.log(np.clip(p3[np.arange(n), y3], eps, 1))))

    # top-1 / top-3 accuracy (1st モデル)
    top1_1 = float(np.mean(np.argmax(p1, axis=1) == y1))
    top3_idx = np.argsort(-p1, axis=1)[:, :3]
    top3_1 = float(np.mean(np.any(top3_idx == y1.reshape(-1, 1), axis=1)))

    return {
        "n_races": n,
        "brier_1st": round(brier_1, 6),
        "brier_2nd": round(brier_2, 6),
        "brier_3rd": round(brier_3, 6),
        "log_loss_1st": round(ll_1, 6),
        "log_loss_2nd": round(ll_2, 6),
        "log_loss_3rd": round(ll_3, 6),
        "top1_acc": round(top1_1, 4),
        "top3_acc": round(top3_1, 4),
    }


def run_accuracy_walkforward(df, feature_cols, verbose=True):
    """2年WFモデル精度評価を実行
    戻り値: weekly_rows (list of dict), monthly_rows (list of dict)
    """
    earliest = df["Date"].min()
    latest = df["Date"].max()
    eval_start = (earliest + pd.DateOffset(months=ACC_WARMUP_MONTHS)).normalize()
    # 月初に揃える
    eval_start = pd.Timestamp(eval_start.year, eval_start.month, 1)

    if verbose:
        print(f"[A] 2年WF 範囲: {eval_start.date()} 〜 {latest.date()}")

    weekly_rows = []
    # 月ごとにループ
    current_month = eval_start
    cached_models = None
    cached_month = None

    while current_month <= latest:
        next_month = (current_month + pd.DateOffset(months=1)).normalize()
        next_month = pd.Timestamp(next_month.year, next_month.month, 1)

        train_df = df[df["Date"] < current_month]
        if len(train_df) < 1000:
            if verbose:
                print(f"  {current_month.date()}: 学習データ不足 ({len(train_df)} 件)、スキップ")
            current_month = next_month
            continue

        if verbose:
            print(f"  {current_month.date()}: 学習 ({len(train_df):,} 件)... ", end="", flush=True)
        m1, m2, m3 = train_three_models(train_df, feature_cols)
        if verbose:
            print("完了", flush=True)

        # この月の評価期間を週単位に分割
        month_end = min(next_month, latest + timedelta(days=1))
        week_blocks = gen_week_blocks(current_month, month_end)

        for w_start, w_end in week_blocks:
            val_df = df[(df["Date"] >= w_start) & (df["Date"] < w_end)]
            if len(val_df) == 0:
                continue
            m = compute_accuracy_metrics(val_df, feature_cols, m1, m2, m3)
            if m is None:
                continue
            m["week_start"] = w_start.date().isoformat()
            m["month"] = current_month.strftime("%Y-%m")
            weekly_rows.append(m)

        current_month = next_month

    # 月次集計
    monthly_rows = []
    if weekly_rows:
        wdf = pd.DataFrame(weekly_rows)
        for month, grp in wdf.groupby("month"):
            total_n = grp["n_races"].sum()
            if total_n == 0:
                continue
            wm = {"month": month, "n_races": int(total_n)}
            for col in ["brier_1st", "brier_2nd", "brier_3rd",
                        "log_loss_1st", "log_loss_2nd", "log_loss_3rd",
                        "top1_acc", "top3_acc"]:
                # 加重平均 (n_races 重み)
                wm[col] = round(float((grp[col] * grp["n_races"]).sum() / total_n), 6)
            monthly_rows.append(wm)

    return weekly_rows, monthly_rows


# =========================================================
# (B) 45日WF 実オッズROI評価
# =========================================================
def evaluate_roi_for_period(val_df, feature_cols, m1, m2, m3,
                            odds_df, results_df, filters):
    """指定val期間 + filtersで ROI を計算
    戻り値: dict (roi, hit_rate, n_trades, ...)
    """
    if len(val_df) == 0:
        return None
    odds_race_ids = set(odds_df["ID"].astype(str).unique())
    val_with_odds = val_df[val_df["ID"].astype(str).isin(odds_race_ids)].copy()
    if len(val_with_odds) == 0:
        return None

    # フィルタ取り出し
    ev_thr = filters["ev_thr"]
    prob_min = filters["prob_min"]
    odds_max = filters["odds_max"]

    # 既存 RE.simulate_realistic_buys を流用
    buys = RE.simulate_realistic_buys(
        val_with_odds, feature_cols, m1, m2, m3, odds_df,
        odds_max=odds_max, prob_min=prob_min, ev_threshold=ev_thr
    )
    metrics = RE.evaluate_buys(buys, results_df)
    return metrics


def run_roi_walkforward(df, feature_cols, mode, verbose=True):
    """45日WF 実オッズROI評価を実行
    mode: 'det' or 'llm'
    戻り値: weekly_rows
    """
    odds_df = pd.read_csv(ODDS_FILE)
    results_df = pd.read_csv(RESULTS_FILE)

    odds_df["Date"] = pd.to_datetime(odds_df["Date"]) if "Date" in odds_df.columns else None
    odds_start = pd.Timestamp(odds_df["Date"].min().date())
    odds_end = pd.Timestamp(odds_df["Date"].max().date())

    # 評価開始: オッズ開始 + 最低学習データ確保
    eval_start = odds_start + timedelta(days=ROI_MIN_TRAIN_DAYS)
    # 週初に揃える (月曜)
    eval_start = eval_start - timedelta(days=eval_start.weekday())
    eval_end = odds_end + timedelta(days=1)

    if verbose:
        print(f"[B] 45日WF ({mode}) 範囲: {eval_start.date()} 〜 {odds_end.date()}")

    filters = DET_FILTERS if mode == "det" else LLM_FILTERS

    week_blocks = gen_week_blocks(eval_start, eval_end)
    weekly_rows = []

    for w_start, w_end in week_blocks:
        train_df = df[df["Date"] < w_start]
        if len(train_df) < 1000:
            continue

        val_df = df[(df["Date"] >= w_start) & (df["Date"] < w_end)]
        if len(val_df) == 0:
            continue

        if verbose:
            print(f"  週 {w_start.date()}〜{(w_end - timedelta(days=1)).date()}: "
                  f"学習 ({len(train_df):,}) ... ", end="", flush=True)

        m1, m2, m3 = train_three_models(train_df, feature_cols)

        # オッズもこの週分に絞る
        week_odds = odds_df[(odds_df["Date"] >= w_start) & (odds_df["Date"] < w_end)]
        if len(week_odds) == 0:
            if verbose:
                print("オッズなしスキップ", flush=True)
            continue

        m = evaluate_roi_for_period(val_df, feature_cols, m1, m2, m3,
                                    week_odds, results_df, filters)
        if m is None or m["invest"] == 0:
            if verbose:
                print("買い目なし", flush=True)
            continue

        m["week_start"] = w_start.date().isoformat()
        m["month"] = w_start.strftime("%Y-%m")
        m["mode"] = mode
        weekly_rows.append(m)
        if verbose:
            print(f"ROI={m['roi']:.2f}%, n_trades={m['n_trades']}", flush=True)

    return weekly_rows


# =========================================================
# bootstrap CI
# =========================================================
def bootstrap_roi_ci(weekly_rows, n_resamples=1000, ci=0.95, seed=42):
    """週次の (invest, return) から bootstrap で累積ROIのCIを算出"""
    if not weekly_rows:
        return None
    pairs = [(r["invest"], r["return"]) for r in weekly_rows if r.get("invest", 0) > 0]
    if not pairs:
        return None
    rng = np.random.default_rng(seed)
    n = len(pairs)
    invests = np.array([p[0] for p in pairs])
    returns = np.array([p[1] for p in pairs])
    rois = []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        inv_sum = invests[idx].sum()
        ret_sum = returns[idx].sum()
        if inv_sum > 0:
            rois.append(ret_sum / inv_sum * 100)
    if not rois:
        return None
    lo = float(np.percentile(rois, (1 - ci) / 2 * 100))
    hi = float(np.percentile(rois, (1 + ci) / 2 * 100))
    return {"ci_lower": round(lo, 2), "ci_upper": round(hi, 2),
            "ci_median": round(float(np.median(rois)), 2), "n_resamples": n_resamples}


def bootstrap_metric_ci(weekly_rows, metric_col, weight_col="n_races",
                        n_resamples=1000, ci=0.95, seed=42):
    """週次の加重メトリック (Brier等) の CI"""
    if not weekly_rows:
        return None
    pairs = [(r[metric_col], r[weight_col]) for r in weekly_rows
             if r.get(weight_col, 0) > 0 and r.get(metric_col) is not None]
    if not pairs:
        return None
    rng = np.random.default_rng(seed)
    n = len(pairs)
    vals = np.array([p[0] for p in pairs])
    weights = np.array([p[1] for p in pairs])
    means = []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        w_sum = weights[idx].sum()
        if w_sum > 0:
            means.append((vals[idx] * weights[idx]).sum() / w_sum)
    if not means:
        return None
    lo = float(np.percentile(means, (1 - ci) / 2 * 100))
    hi = float(np.percentile(means, (1 + ci) / 2 * 100))
    return {"ci_lower": round(lo, 6), "ci_upper": round(hi, 6),
            "ci_median": round(float(np.median(means)), 6), "n_resamples": n_resamples}


# =========================================================
# 集計 / 出力
# =========================================================
def summarize_accuracy(weekly_rows, monthly_rows):
    if not weekly_rows:
        return {"note": "no data"}
    total_n = sum(r["n_races"] for r in weekly_rows)
    summary = {"n_weeks": len(weekly_rows), "n_months": len(monthly_rows),
               "total_races": int(total_n)}
    for col in ["brier_1st", "brier_2nd", "brier_3rd",
                "log_loss_1st", "log_loss_2nd", "log_loss_3rd",
                "top1_acc", "top3_acc"]:
        vals = [(r[col], r["n_races"]) for r in weekly_rows]
        weighted = sum(v * n for v, n in vals) / total_n if total_n > 0 else 0
        summary[col] = round(float(weighted), 6)
        ci = bootstrap_metric_ci(weekly_rows, col)
        if ci:
            summary[f"{col}_ci"] = ci
    return summary


def summarize_roi(weekly_rows):
    if not weekly_rows:
        return {"note": "no data"}
    total_invest = sum(r["invest"] for r in weekly_rows)
    total_return = sum(r["return"] for r in weekly_rows)
    total_trades = sum(r["n_trades"] for r in weekly_rows)
    total_hits = sum(r["n_hits"] for r in weekly_rows)
    cum_roi = total_return / total_invest * 100 if total_invest > 0 else 0
    summary = {
        "n_weeks": len(weekly_rows),
        "n_trades": int(total_trades),
        "n_hits": int(total_hits),
        "hit_rate": round(total_hits / total_trades * 100, 2) if total_trades > 0 else 0,
        "invest": int(total_invest),
        "return": int(total_return),
        "profit": int(total_return - total_invest),
        "roi": round(cum_roi, 2),
    }
    ci = bootstrap_roi_ci(weekly_rows)
    if ci:
        summary["roi_ci"] = ci
    # 月次勝率 (週次の月集計でROI > 100% の月数 / 全月数)
    if weekly_rows:
        wdf = pd.DataFrame(weekly_rows)
        monthly = wdf.groupby("month").agg({"invest": "sum", "return": "sum"})
        monthly["roi"] = monthly["return"] / monthly["invest"] * 100
        monthly = monthly[monthly["invest"] > 0]
        n_months = len(monthly)
        n_profitable = int((monthly["roi"] >= 100).sum())
        summary["n_months"] = n_months
        summary["n_profitable_months"] = n_profitable
        summary["monthly_win_rate"] = (
            round(n_profitable / n_months * 100, 2) if n_months > 0 else 0
        )
    return summary


def save_results(weekly_rows, csv_path, mode_label=""):
    if not weekly_rows:
        print(f"  [{mode_label}] 結果なし、CSV出力スキップ")
        return
    df = pd.DataFrame(weekly_rows)
    df.to_csv(csv_path, index=False)
    print(f"  [{mode_label}] {csv_path} に {len(df)} 行を出力")


# =========================================================
# main
# =========================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["accuracy", "roi", "both"], default="both")
    parser.add_argument("--quick", action="store_true",
                        help="テスト用: accuracyは直近6ヶ月のみ実行")
    args = parser.parse_args()

    print("=" * 70)
    print(" walk-forward backtest 評価器 (ハイブリッド版)")
    print("=" * 70)
    start_ts = datetime.now()

    print(f"\n[load] {FEATURES_FILE}")
    df, feature_cols = load_features()
    print(f"  shape: {df.shape}, 特徴量: {len(feature_cols)} 個")
    print(f"  期間: {df['Date'].min().date()} 〜 {df['Date'].max().date()}")

    summary = {"generated_at": datetime.now().isoformat()}

    if args.mode in ("accuracy", "both"):
        print("\n" + "-" * 70)
        print(" [A] 2年WF モデル精度評価")
        print("-" * 70)
        df_a = df
        if args.quick:
            # quick: 直近6ヶ月だけ
            cutoff = df["Date"].max() - pd.DateOffset(months=6)
            df_a = df[df["Date"] >= cutoff - pd.DateOffset(months=ACC_WARMUP_MONTHS)]
            print(f"  [QUICK] 直近6ヶ月のみ: {df_a['Date'].min().date()}〜")
        weekly_a, monthly_a = run_accuracy_walkforward(df_a, feature_cols)
        save_results(weekly_a, MODEL_RESULTS_CSV, "accuracy")
        summary["accuracy"] = summarize_accuracy(weekly_a, monthly_a)
        print(f"\n  [accuracy] サマリ:")
        for k, v in summary["accuracy"].items():
            if not isinstance(v, dict):
                print(f"    {k}: {v}")

    if args.mode in ("roi", "both"):
        print("\n" + "-" * 70)
        print(" [B] 45日WF 実オッズROI評価")
        print("-" * 70)
        roi_all = []
        for mode in ["det", "llm"]:
            print(f"\n  -- mode={mode} --")
            weekly_r = run_roi_walkforward(df, feature_cols, mode)
            for r in weekly_r:
                roi_all.append(r)
            summary.setdefault("roi", {})[mode] = summarize_roi(weekly_r)
            print(f"\n  [roi {mode}] サマリ:")
            for k, v in summary["roi"][mode].items():
                if not isinstance(v, dict):
                    print(f"    {k}: {v}")
        save_results(roi_all, ROI_RESULTS_CSV, "roi (det+llm)")

    elapsed = (datetime.now() - start_ts).total_seconds()
    print(f"\n=== 完了 (所要時間: {elapsed:.1f}秒) ===")

    # 集計をJSONで参考保存
    json_path = os.path.join(OUTPUT_DIR, "wf_summary.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"summary -> {json_path}")


if __name__ == "__main__":
    main()
