"""
compare_llm_vs_det.py - LLM版 vs 決定論フィルタ版 paper trade 比較

データソース:
  - daily_predictions.csv: Stakes (LLM) / Stakes_Det (決定論フィルタ) の買い目
  - daily_history_results.csv: 実際のレース結果 (存在すれば最優先で使用)
  - dashboard_data.json: recent_races に result_eye が埋め込まれている (後方互換フォールバック)

実行方法:
  python auto_research/compare_llm_vs_det.py
"""

import os
import sys
import json
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PRED_FILE  = os.path.join(ROOT, "dashboard", "public", "daily_data", "daily_predictions.csv")
RES_FILE   = os.path.join(ROOT, "daily_data", "daily_history_results.csv")
DASH_FILE  = os.path.join(ROOT, "dashboard", "public", "daily_data", "dashboard_data.json")

# 並走開始日
PAPER_START = "2026-04-28"


def load_results() -> dict:
    """レース結果を辞書で返す {race_id: (result_combo_nodash, payout_per_100yen)}"""
    results = {}

    # 1st priority: daily_history_results.csv
    if os.path.exists(RES_FILE):
        df_r = pd.read_csv(RES_FILE)
        df_r = df_r.drop_duplicates(subset=["ID"], keep="last")
        for _, row in df_r.iterrows():
            rid = str(row["ID"])
            combo = str(row["Result"]).replace("-", "")
            try:
                payout = int(float(row["Payout"]))
            except (ValueError, TypeError):
                payout = 0
            results[rid] = (combo, payout)
        print(f"[INFO] daily_history_results.csv から {len(results)} レース分の結果を読み込みました")
        return results

    # 2nd priority: dashboard_data.json recent_races (result_eye + odds)
    if os.path.exists(DASH_FILE):
        with open(DASH_FILE, encoding="utf-8") as f:
            dash = json.load(f)
        rr = dash.get("recent_races", [])
        for r in rr:
            rid = r.get("id", "")
            combo = str(r.get("result_eye", "")).replace("-", "")
            # odds = 実際払戻 ÷ 100 (payout_per_100yen と等価)
            odds_val = r.get("odds", 0)
            payout = int(round(odds_val * 100)) if odds_val else 0
            if rid and combo:
                results[rid] = (combo, payout)
        if results:
            print(f"[WARN] daily_history_results.csv が存在しないため、"
                  f"dashboard_data.json の recent_races ({len(results)} レース) を代替使用します。")
            print(f"[WARN] 完全な比較には daily_history_results.csv が必要です。")
        return results

    return {}


def parse_stakes(raw) -> dict:
    """Stakes/Stakes_Det JSON文字列 → {combo_nodash: stake_yen}"""
    if pd.isna(raw) or str(raw).strip() in ("", "nan", "{}"):
        return {}
    try:
        d = json.loads(str(raw))
        return {str(k).replace("-", ""): int(v) for k, v in d.items()}
    except Exception:
        return {}


def compute_metrics(races: list, results: dict) -> dict:
    """レースリスト(辞書)と結果辞書からROI指標を計算"""
    total_invest = 0
    total_return = 0
    n_trades = 0
    n_hits = 0
    daily: dict = {}

    for r in races:
        rid = r["race_id"]
        stakes = r["stakes"]  # {combo: yen}
        date = r["date"]

        if not stakes:
            continue
        if rid not in results:
            continue

        result_combo, payout = results[rid]
        invest = sum(stakes.values())
        ret = 0

        if result_combo in stakes:
            unit_bet = stakes[result_combo]
            ret = (unit_bet // 100) * payout
            n_hits += 1

        total_invest += invest
        total_return += ret
        n_trades += 1

        d = daily.setdefault(date, {"invest": 0, "return": 0, "n": 0, "hits": 0})
        d["invest"] += invest
        d["return"] += ret
        d["n"] += 1
        if result_combo in stakes:
            d["hits"] += 1

    roi = round(total_return / total_invest * 100, 1) if total_invest > 0 else 0.0
    hit_rate = round(n_hits / n_trades * 100, 1) if n_trades > 0 else 0.0
    profit = total_return - total_invest

    return {
        "roi": roi,
        "hit_rate": hit_rate,
        "n_trades": n_trades,
        "n_hits": n_hits,
        "invest": total_invest,
        "return": total_return,
        "profit": profit,
        "daily": daily,
    }


def main():
    print("=" * 60)
    print(" LLM vs Det Paper Trade 比較スクリプト")
    print("=" * 60)

    # --- 1. データ読み込み ---
    if not os.path.exists(PRED_FILE):
        print(f"[ERROR] {PRED_FILE} が見つかりません")
        sys.exit(1)

    df = pd.read_csv(PRED_FILE)
    paper = df[df["Date"] >= PAPER_START].copy()
    print(f"\n[INFO] 予測CSV: {len(paper)} 行 (>= {PAPER_START})")

    det_notnull = paper["Stakes_Det"].notna() & (paper["Stakes_Det"].astype(str).str.strip() != "nan")
    print(f"[INFO] Stakes_Det 非空行数: {det_notnull.sum()}")

    if det_notnull.sum() < 10:
        print("\n[ABORT] Stakes_Det のデータが少なすぎます（10件未満）。")
        print("並走運用が想定通り走っていない可能性があります。")
        sys.exit(0)

    # --- 2. 結果データ読み込み ---
    results = load_results()
    if not results:
        print("\n[ABORT] レース結果データが見つかりません。")
        print("daily_history_results.csv または dashboard_data.json の recent_races が必要です。")
        sys.exit(0)

    # --- 3. 買い目リスト構築 ---
    llm_races = []
    det_races = []

    for _, row in paper.iterrows():
        rid = str(row["RaceID"])
        date = str(row["Date"])
        llm_stakes = parse_stakes(row.get("Stakes"))
        det_stakes = parse_stakes(row.get("Stakes_Det"))
        llm_races.append({"race_id": rid, "date": date, "stakes": llm_stakes})
        det_races.append({"race_id": rid, "date": date, "stakes": det_stakes})

    # --- 4. 指標計算 ---
    llm = compute_metrics(llm_races, results)
    det = compute_metrics(det_races, results)

    # --- 5. 結果表示 ---
    result_dates = sorted({rid.split("_")[0] for rid in results})
    result_date_str = ""
    if result_dates:
        # Convert YYYYMMDD to YYYY-MM-DD
        def fmt(d):
            return f"{d[:4]}-{d[4:6]}-{d[6:]}"
        result_date_str = f"{fmt(result_dates[0])} 〜 {fmt(result_dates[-1])}"

    covered_races_llm = [r for r in llm_races if r["race_id"] in results and r["stakes"]]
    covered_races_det = [r for r in det_races if r["race_id"] in results and r["stakes"]]

    print("\n" + "=" * 60)
    print(" 集計結果")
    print("=" * 60)
    print(f"\n結果データ期間: {result_date_str}")
    print(f"マッチしたレース数: LLM={llm['n_trades']}, Det={det['n_trades']}")
    print()
    print(f"{'指標':<12} {'LLM版':>10} {'Det版':>10}")
    print("-" * 35)
    print(f"{'ROI':<12} {llm['roi']:>9.1f}% {det['roi']:>9.1f}%")
    print(f"{'的中率':<12} {llm['hit_rate']:>9.1f}% {det['hit_rate']:>9.1f}%")
    print(f"{'損益':<12} {llm['profit']:>+10,}円 {det['profit']:>+10,}円")
    print(f"{'投資額':<12} {llm['invest']:>10,}円 {det['invest']:>10,}円")
    print(f"{'払戻額':<12} {llm['return']:>10,}円 {det['return']:>10,}円")
    print(f"{'取引数':<12} {llm['n_trades']:>10} {det['n_trades']:>10}")
    print(f"{'的中数':<12} {llm['n_hits']:>10} {det['n_hits']:>10}")
    print()

    # --- 6. 日別推移 ---
    all_dates = sorted(set(list(llm["daily"].keys()) + list(det["daily"].keys())))
    if all_dates:
        print("【日別推移】")
        print(f"{'日付':<12} {'LLM_投資':>9} {'LLM_ROI':>9} {'Det_投資':>9} {'Det_ROI':>9}")
        print("-" * 55)
        for d in all_dates:
            ld = llm["daily"].get(d, {})
            dd = det["daily"].get(d, {})
            l_roi = round(ld["return"] / ld["invest"] * 100, 1) if ld.get("invest", 0) > 0 else 0.0
            d_roi = round(dd["return"] / dd["invest"] * 100, 1) if dd.get("invest", 0) > 0 else 0.0
            l_inv = ld.get("invest", 0)
            d_inv = dd.get("invest", 0)
            print(f"{d:<12} {l_inv:>8,}円 {l_roi:>8.1f}% {d_inv:>8,}円 {d_roi:>8.1f}%")
    print()

    # --- 7. 全体サマリー (paper trade 期間 全体の Stakes ベース) ---
    llm_total_invest_all = paper["Stakes"].apply(parse_stakes).apply(
        lambda d: sum(d.values()) if d else 0).sum()
    det_total_invest_all = paper["Stakes_Det"].apply(parse_stakes).apply(
        lambda d: sum(d.values()) if d else 0).sum()
    print("【期間全体の買い目サマリー (結果マッチ有無に関係なく)】")
    print(f"  LLM: 買い目あり={paper['Stakes'].apply(parse_stakes).apply(bool).sum()}R / "
          f"総投資={llm_total_invest_all:,}円 (仮想)")
    print(f"  Det: 買い目あり={paper['Stakes_Det'].apply(parse_stakes).apply(bool).sum()}R / "
          f"総投資={det_total_invest_all:,}円 (仮想)")
    print()
    print(f"[NOTE] ROI計算の対象: 結果データがマッチした {llm['n_trades']} / {det['n_trades']} レースのみ")


if __name__ == "__main__":
    main()
