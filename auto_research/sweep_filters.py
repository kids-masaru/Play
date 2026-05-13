"""
sweep_filters.py - odds_max × prob_min × ev_threshold の sweep（高速版）

最適化:
- 全レースの combo×ev×odds×prob を一度だけ pre-compute
- フィルタ条件は dict 上で適用するだけ → 各config 数秒
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

from auto_research import realistic_evaluator as RE

FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
RESULTS_FILE = os.path.join(ROOT, "past_data", "past_history_results.csv")
ODDS_FILE = os.path.join(ROOT, "past_data", "past_odds_3t.csv")

VAL_DAYS = 30
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


def precompute_race_combos(val_df, feat_cols, m1, m2, m3, odds_df):
    """各 (race_id, combo) について prob, odds, ev を計算したリストを返す。
    フィルタ sweep ではこれを使い回す。
    """
    val_df = val_df.reset_index(drop=True).copy()
    X = val_df[feat_cols]
    p1 = m1.predict(X)
    p2 = m2.predict(X)
    p3 = m3.predict(X)

    odds_by_race = {}
    for rid, grp in odds_df.groupby("ID"):
        d = {}
        for _, r in grp.iterrows():
            try:
                d[str(r["Combination"])] = float(r["Odds"])
            except (ValueError, TypeError):
                continue
        odds_by_race[str(rid)] = d

    val_df["__idx"] = val_df.index

    # date -> [(rid, [(combo, ev, odds, prob)...])]
    by_date = {}
    for date, day_grp in val_df.groupby("Date"):
        race_pool = []
        for _, row in day_grp.iterrows():
            idx = row["__idx"]
            rid = str(row["ID"])
            if rid not in odds_by_race:
                continue
            combos = RE.estimate_trifecta_probs_full(p1[idx], p2[idx], p3[idx])
            race_odds = odds_by_race[rid]
            ev_combos = []
            for combo, prob in combos:
                if combo in race_odds:
                    odds = race_odds[combo]
                    ev = prob * odds
                    ev_combos.append((combo, ev, odds, prob))
            if ev_combos:
                race_pool.append((rid, ev_combos))
        by_date[str(date)[:10]] = race_pool

    return by_date


def evaluate_with_filter(by_date, results_df, ev_thr, odds_max, prob_min):
    """pre-computed by_date に filter を適用し、買い目を生成して評価"""
    # results dict
    res_dict = {}
    for _, r in results_df.drop_duplicates(subset=["ID"], keep="last").iterrows():
        rid = str(r["ID"])
        try:
            payout = int(float(r["Payout"]))
        except (ValueError, TypeError):
            payout = 0
        result_combo = str(r["Result"]).replace("-", "")
        res_dict[rid] = (result_combo, payout)

    total_invest = 0
    total_return = 0
    n_trades = 0
    n_hits = 0
    n_races = 0

    for date, race_pool in by_date.items():
        # フィルタ適用
        filtered_pool = []
        for rid, ev_combos in race_pool:
            kept = []
            for combo, ev, odds, prob in ev_combos:
                if ev <= ev_thr:
                    continue
                if odds_max is not None and odds > odds_max:
                    continue
                if prob_min is not None and prob < prob_min:
                    continue
                kept.append((combo, ev, odds, prob))
            if kept:
                kept.sort(key=lambda x: x[1], reverse=True)
                max_ev = kept[0][1]
                filtered_pool.append((rid, max_ev, kept))

        # トップNレース
        filtered_pool.sort(key=lambda x: x[1], reverse=True)
        for rid, _, kept in filtered_pool[:RE.TOP_N_RACES_PER_DAY]:
            if rid not in res_dict:
                continue
            result_combo, payout = res_dict[rid]
            n_races += 1
            for combo, ev, odds, prob in kept[:RE.TOP_N_COMBOS_PER_RACE]:
                stake = RE.kelly_stake(prob, odds)
                if stake <= 0:
                    continue
                total_invest += stake
                n_trades += 1
                combo_compact = combo.replace("-", "")
                if combo_compact == result_combo:
                    total_return += (stake // 100) * payout
                    n_hits += 1

    if total_invest == 0:
        return None
    return {
        "n_trades": n_trades, "n_hits": n_hits,
        "hit_rate": round(n_hits / n_trades * 100, 2),
        "invest": total_invest, "return": total_return,
        "profit": total_return - total_invest,
        "roi": round(total_return / total_invest * 100, 2),
        "n_races": n_races,
    }


def main():
    print("[1/3] Loading & training models (1 time)...", flush=True)
    df = pd.read_csv(FEATURES_FILE)
    df = df.dropna(subset=["Target_1st", "Target_2nd", "Target_3rd"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    split_date = df["Date"].max() - timedelta(days=VAL_DAYS)
    train_df = df[df["Date"] < split_date].copy()
    val_df = df[df["Date"] >= split_date].copy()
    feat = [c for c in df.columns if c not in EXCLUDE_COLS and df[c].dtype in ["int64", "float64"]]

    def train_one(target_col):
        X = train_df[feat]; y = train_df[target_col].astype(int) - 1
        X_tr, X_va, y_tr, y_va = train_test_split(X, y, test_size=0.1, random_state=RANDOM_STATE)
        return lgb.train(
            LGB_PARAMS, lgb.Dataset(X_tr, label=y_tr),
            num_boost_round=NUM_BOOST_ROUND,
            valid_sets=[lgb.Dataset(X_va, label=y_va)],
            callbacks=[lgb.early_stopping(EARLY_STOPPING), lgb.log_evaluation(0)],
        )

    m1 = train_one("Target_1st"); m2 = train_one("Target_2nd"); m3 = train_one("Target_3rd")

    odds_df = pd.read_csv(ODDS_FILE)
    odds_race_ids = set(odds_df["ID"].astype(str).unique())
    val_with_odds = val_df[val_df["ID"].astype(str).isin(odds_race_ids)].copy()
    print(f"  val ∩ odds: {len(val_with_odds)} レース")

    print("[2/3] Pre-compute combos for all val races...", flush=True)
    by_date = precompute_race_combos(val_with_odds, feat, m1, m2, m3, odds_df)
    print(f"  cached: {sum(len(v) for v in by_date.values())} race-pools across {len(by_date)} dates")

    results_df = pd.read_csv(RESULTS_FILE)

    print("[3/3] Sweep filter combinations...", flush=True)
    odds_caps = [None, 30, 50, 100, 200, 500]
    prob_floors = [None, 0.005, 0.01, 0.02, 0.05]
    ev_thresholds = [1.0, 1.5, 2.0]

    rows = []
    for ev_t in ev_thresholds:
        for oc in odds_caps:
            for pf in prob_floors:
                m = evaluate_with_filter(by_date, results_df, ev_t, oc, pf)
                if m is None:
                    continue
                rows.append({
                    "ev_thr": ev_t,
                    "odds_max": str(oc) if oc is not None else "-",
                    "prob_min": f"{pf:.3f}" if pf is not None else "-",
                    "n_trades": m["n_trades"],
                    "n_hits": m["n_hits"],
                    "hit_rate%": m["hit_rate"],
                    "invest": m["invest"],
                    "return": m["return"],
                    "profit": m["profit"],
                    "roi%": m["roi"],
                })

    res = pd.DataFrame(rows)
    print(f"\n全 {len(res)} configs 完了\n")

    print("=" * 100)
    print(" 全 sweep 結果 (損益降順)")
    print("=" * 100)
    print(res.sort_values("profit", ascending=False).to_string(index=False))

    print("\n--- 利益(profit)トップ5 ---")
    print(res.sort_values("profit", ascending=False).head(5).to_string(index=False))

    print("\n--- ROI 100%以上 + n_trades>=50 ---")
    good = res[(res["roi%"] >= 100) & (res["n_trades"] >= 50)].sort_values("profit", ascending=False).head(10)
    if not good.empty:
        print(good.to_string(index=False))
    else:
        print("該当なし")


if __name__ == "__main__":
    main()
