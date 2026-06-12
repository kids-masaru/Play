"""3連単オッズから2連単オッズを近似し、ROI評価する。

近似式:
  odds_2t(A-B) ≒ 1 / Σ_{x∈{1..6}, x≠A, x≠B} (1/odds_3t(A-B-x))

これは「2連単(A-B)が当たる ⇔ 3連単(A-B-x) のいずれかが当たる」
の関係から、各組合せの暗黙確率を集約したもの。

評価ロジック:
- 学習データ全期間 - 直近365日で3モデル学習
- 直近365日で評価
- 各レース×30通りの2連単について:
    pred_2t(A-B) = m1[A] × m2[B] (独立仮定)
    ev = pred_2t × odds_2t
- 3連単と同じフィルタsweep
- ROI/的中率比較
"""
import os
import sys
from datetime import timedelta
from itertools import permutations

import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import train_test_split

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from auto_research import realistic_evaluator as RE

FEATURES_FILE = os.path.join(ROOT, "past_data", "ml_features.csv")
RESULTS_FILE = os.path.join(ROOT, "past_data", "past_history_results.csv")
ODDS_FILE = os.path.join(ROOT, "past_data", "past_odds_3t.csv")

VAL_DAYS = 365
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


def approximate_2t_odds(odds_df):
    """3連単オッズから2連単近似オッズを生成。
    返り値: dict[ID] -> dict["A-B"] -> odds
    """
    odds_df = odds_df[odds_df["Odds"] > 0].copy()
    odds_df["InvOdds"] = 1.0 / odds_df["Odds"]
    odds_df["A"] = odds_df["Combination"].str.split("-").str[0].astype(int)
    odds_df["B"] = odds_df["Combination"].str.split("-").str[1].astype(int)

    # ID, A, B でグループ化
    agg = odds_df.groupby(["ID", "A", "B"], as_index=False)["InvOdds"].sum()
    agg["Odds2t"] = 1.0 / agg["InvOdds"]

    # dict 化
    result = {}
    for _, row in agg.iterrows():
        rid = str(row["ID"])
        key = f"{int(row['A'])}-{int(row['B'])}"
        result.setdefault(rid, {})[key] = float(row["Odds2t"])
    return result


def compute_2t_results(results_df):
    """Result(例: "1-2-3", "1-2") から「2連単で何が当たったか」「払戻し」を導出。
    払戻しは2連単オッズ近似 × 100 として近似的に計算する。
    ※ 実際の2連単払戻しはデータがないので、ここでは近似オッズ × 100円とする。
    """
    out = {}
    for _, r in results_df.drop_duplicates(subset=["ID"], keep="last").iterrows():
        rid = str(r["ID"])
        result_str = str(r["Result"])
        parts = result_str.split("-")
        if len(parts) < 2:
            continue
        try:
            a = int(parts[0]); b = int(parts[1])
        except (ValueError, TypeError):
            continue
        winning_key = f"{a}-{b}"
        out[rid] = winning_key
    return out


def evaluate(by_race, results_2t, odds_2t_map, ev_thr, odds_max, prob_min):
    """フィルタ適用 → 買い目生成 → 評価"""
    total_invest = 0
    total_return = 0
    n_trades = 0
    n_hits = 0
    n_races = 0

    # 日付別にグルーピングしてトップNレース選定
    by_date = {}
    for rid, info in by_race.items():
        date = info["date"]
        by_date.setdefault(date, []).append((rid, info))

    for date, race_list in by_date.items():
        filtered_pool = []
        for rid, info in race_list:
            kept = []
            for key, prob in info["preds"].items():
                if key not in info["odds"]:
                    continue
                odds = info["odds"][key]
                ev = prob * odds
                if ev <= ev_thr:
                    continue
                if odds_max is not None and odds > odds_max:
                    continue
                if prob_min is not None and prob < prob_min:
                    continue
                kept.append((key, ev, odds, prob))
            if kept:
                kept.sort(key=lambda x: x[1], reverse=True)
                max_ev = kept[0][1]
                filtered_pool.append((rid, max_ev, kept))

        filtered_pool.sort(key=lambda x: x[1], reverse=True)
        for rid, _, kept in filtered_pool[:RE.TOP_N_RACES_PER_DAY]:
            if rid not in results_2t:
                continue
            winning_key = results_2t[rid]
            n_races += 1
            for key, ev, odds, prob in kept[:RE.TOP_N_COMBOS_PER_RACE]:
                stake = RE.kelly_stake(prob, odds)
                if stake <= 0:
                    continue
                total_invest += stake
                n_trades += 1
                if key == winning_key:
                    # 近似払戻し: stake × odds (整数100円単位)
                    payout = int(odds * 100)
                    total_return += (stake // 100) * payout
                    n_hits += 1

    if total_invest == 0:
        return None
    return {
        "n_trades": n_trades, "n_hits": n_hits,
        "hit_rate": round(n_hits / n_trades * 100, 3),
        "invest": total_invest, "return": total_return,
        "profit": total_return - total_invest,
        "roi": round(total_return / total_invest * 100, 2),
        "n_races": n_races,
    }


def main():
    print("[1/5] データ読み込み・分割...")
    df = pd.read_csv(FEATURES_FILE)
    df = df.dropna(subset=["Target_1st", "Target_2nd", "Target_3rd"])
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)
    split_date = df["Date"].max() - timedelta(days=VAL_DAYS)
    train_df = df[df["Date"] < split_date].copy()
    val_df = df[df["Date"] >= split_date].copy()
    feat = [c for c in df.columns if c not in EXCLUDE_COLS and df[c].dtype in ["int64", "float64"]]
    print(f"  train: {len(train_df):,} / val: {len(val_df):,} / features: {len(feat)}")

    print("[2/5] 3連単オッズから2連単近似オッズ生成...")
    odds_df = pd.read_csv(ODDS_FILE, usecols=["ID", "Combination", "Odds"])
    odds_2t_map = approximate_2t_odds(odds_df)
    print(f"  2連単近似オッズ保持レース: {len(odds_2t_map):,}")

    val_with_odds = val_df[val_df["ID"].astype(str).isin(odds_2t_map.keys())].copy()
    print(f"  val ∩ odds_2t: {len(val_with_odds):,}")

    print("[3/5] モデル学習...")
    def train_one(target_col):
        X = train_df[feat]; y = train_df[target_col].astype(int) - 1
        X_tr, X_va, y_tr, y_va = train_test_split(X, y, test_size=0.1, random_state=RANDOM_STATE)
        return lgb.train(
            LGB_PARAMS, lgb.Dataset(X_tr, label=y_tr),
            num_boost_round=NUM_BOOST_ROUND,
            valid_sets=[lgb.Dataset(X_va, label=y_va)],
            callbacks=[lgb.early_stopping(EARLY_STOPPING), lgb.log_evaluation(0)],
        )
    m1 = train_one("Target_1st")
    m2 = train_one("Target_2nd")

    print("[4/5] 予測 → 2連単確率算出...")
    X_val = val_with_odds[feat]
    p1 = m1.predict(X_val)
    p2 = m2.predict(X_val)

    by_race = {}
    for i, (_, row) in enumerate(val_with_odds.iterrows()):
        rid = str(row["ID"])
        date = str(row["Date"])[:10]
        if rid not in odds_2t_map:
            continue
        preds = {}
        # 30 通り (A=1..6, B=1..6, A!=B) の 2連単予測確率
        for a in range(6):
            for b in range(6):
                if a == b:
                    continue
                key = f"{a+1}-{b+1}"
                # 独立仮定: P(1着=a) × P(2着=b)
                prob = float(p1[i, a] * p2[i, b])
                preds[key] = prob
        by_race[rid] = {"date": date, "preds": preds, "odds": odds_2t_map[rid]}

    print(f"  by_race レコード: {len(by_race):,}")

    print("[5/5] 結果読み込み・フィルタsweep...")
    results_df = pd.read_csv(RESULTS_FILE)
    results_2t = compute_2t_results(results_df)
    print(f"  結果保持レース: {len(results_2t):,}")

    ev_thresholds = [1.0, 1.2, 1.5, 2.0]
    odds_caps = [None, 30, 50, 100, 200]
    prob_floors = [None, 0.01, 0.02, 0.05, 0.10]

    rows = []
    for ev_t in ev_thresholds:
        for oc in odds_caps:
            for pf in prob_floors:
                m = evaluate(by_race, results_2t, odds_2t_map, ev_t, oc, pf)
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
    print(" 2連単 sweep結果 (損益降順)")
    print("=" * 100)
    print(res.sort_values("profit", ascending=False).to_string(index=False))

    print("\n--- 利益(profit)トップ10 ---")
    print(res.sort_values("profit", ascending=False).head(10).to_string(index=False))

    print("\n--- ROI 100%以上 + n_trades>=50 ---")
    good = res[(res["roi%"] >= 100) & (res["n_trades"] >= 50)].sort_values("profit", ascending=False).head(10)
    if not good.empty:
        print(good.to_string(index=False))
    else:
        print("該当なし")


if __name__ == "__main__":
    main()
