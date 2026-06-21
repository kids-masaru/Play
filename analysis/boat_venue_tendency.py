# -*- coding: utf-8 -*-
"""
ボートレース「当たりやすい指標」での会場・レース番号 傾向集計
------------------------------------------------------------
3連単(346レース/的中11)では母数が薄すぎてノイズだったため、
母数の大きい指標に切り替えて偏りを可視化する。

指標:
  (1) 1号艇1着率(イン逃げ率)  … 全結果ベース。会場の堅さ/荒れの基本指標
  (2) 平均払戻(3連単)          … 高いほど荒れる会場(高配当=波乱)
  (3) Det本命1着率            … Detの予想1着(最も賭けた買い目の1着目)が
                                 実際に1着になった率。モデルの得意会場探し

入力(daily_data 配下):
  - daily_history_results.csv : Venue, R, Result("1着-2着-3着"), Payout
  - daily_predictions.csv     : RaceID, Venue, R, Stakes_Det(買い目 JSON)
出力:
  - コンソール + analysis/out/venue_tendency.csv / race_tendency.csv
"""
import json
import os
import sys
from datetime import datetime
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(BASE, "..", "dashboard", "public", "daily_data"))
OUT = os.path.join(BASE, "out")
os.makedirs(OUT, exist_ok=True)


def first_boat(result):
    """ '3-4-6' -> '3' （1着の艇番） """
    if not isinstance(result, str) or "-" not in result:
        return None
    return result.split("-")[0].strip()


def det_main_boat(stakes_json):
    """ Stakes_Det から Det本命(最も賭けた買い目)の1着目を返す """
    if not isinstance(stakes_json, str) or not stakes_json.strip():
        return None
    try:
        d = json.loads(stakes_json)
    except Exception:
        return None
    if not d:
        return None
    # 最も賭け金が大きい買い目（同額なら最初）
    top = max(d.items(), key=lambda kv: float(kv[1]))[0]
    return str(top)[0]  # 1着目の艇番


def main():
    res = pd.read_csv(os.path.join(DATA, "daily_history_results.csv"))
    res = res.dropna(subset=["Result"]).copy()
    res["win1"] = res["Result"].map(first_boat)
    res["is_in"] = (res["win1"] == "1").astype(int)  # 1号艇1着か

    # --- Det本命1着率の付与（予想CSVを結合） ---
    preds = pd.read_csv(os.path.join(DATA, "daily_predictions.csv"))
    preds["det_main"] = preds["Stakes_Det"].map(det_main_boat)
    pmap = {str(r["RaceID"]): r["det_main"] for _, r in preds.iterrows() if pd.notna(r["det_main"])}
    res["det_main"] = res["ID"].astype(str).map(pmap)
    res["det_hit1"] = res.apply(
        lambda r: (1 if (pd.notna(r["det_main"]) and r["det_main"] == r["win1"]) else 0), axis=1
    )
    res["det_has"] = res["det_main"].notna().astype(int)

    n = len(res)
    print("=== 全体 ===")
    print(f"対象レース(結果確定): {n:,}")
    print(f"1号艇1着率(イン逃げ率): {res['is_in'].mean()*100:.1f}%")
    det_races = res[res["det_has"] == 1]
    if len(det_races):
        print(f"Det本命1着率: {det_races['det_hit1'].mean()*100:.1f}%  "
              f"(対象 {len(det_races):,}レース)")
    print(f"平均払戻(3連単): ¥{res['Payout'].mean():,.0f}")
    print()

    def summarize(by):
        g = res.groupby(by).agg(
            races=("is_in", "size"),
            in_rate=("is_in", "mean"),
            avg_payout=("Payout", "mean"),
            med_payout=("Payout", "median"),  # 平均は高配当1本で歪むため中央値も
            det_races=("det_has", "sum"),
            det_hits=("det_hit1", "sum"),
        ).reset_index()
        g["1号艇1着率(%)"] = (g["in_rate"] * 100).round(1)
        g["平均払戻"] = g["avg_payout"].round(0).astype(int)
        g["中央払戻"] = g["med_payout"].round(0).astype(int)
        g["Det本命1着率(%)"] = g.apply(
            lambda r: round(r["det_hits"] / r["det_races"] * 100, 1) if r["det_races"] > 0 else None, axis=1
        )
        return g

    by_venue = summarize("Venue").sort_values("1号艇1着率(%)", ascending=False)
    by_race = summarize("R").sort_values("R")

    pd.set_option("display.unicode.east_asian_width", True)
    cols = ["races", "1号艇1着率(%)", "平均払戻", "det_races", "Det本命1着率(%)"]

    print("=== 会場別（1号艇1着率の高い順＝堅い会場）===")
    print(by_venue[["Venue"] + cols].to_string(index=False))
    print()
    print("=== レース番号別 ===")
    print(by_race[["R"] + cols].to_string(index=False))

    by_venue.drop(columns=["in_rate", "avg_payout", "med_payout"]).to_csv(
        os.path.join(OUT, "venue_tendency.csv"), index=False, encoding="utf-8-sig")
    by_race.drop(columns=["in_rate", "avg_payout", "med_payout"]).to_csv(
        os.path.join(OUT, "race_tendency.csv"), index=False, encoding="utf-8-sig")
    print(f"\nCSV出力: {OUT}\\venue_tendency.csv / race_tendency.csv")

    # --- ダッシュボード用 JSON 出力（傾向タブが読む） ---
    def to_records(g, key, key_name):
        out = []
        for _, r in g.iterrows():
            det_rate = r["Det本命1着率(%)"]
            out.append({
                key_name: (int(r[key]) if key_name == "r" else r[key]),
                "races": int(r["races"]),
                "in_rate": round(float(r["in_rate"]) * 100, 1),
                "med_payout": int(r["中央払戻"]),
                "det_races": int(r["det_races"]),
                "det_in_rate": (None if pd.isna(det_rate) else float(det_rate)),
            })
        return out

    payload = {
        "generated_date": datetime.now().strftime("%Y-%m-%d"),
        "date_from": str(res["Date"].min()) if "Date" in res else None,
        "date_to": str(res["Date"].max()) if "Date" in res else None,
        "overall": {
            "races": int(n),
            "in_rate": round(float(res["is_in"].mean()) * 100, 1),
            "det_in_rate": (round(float(det_races["det_hit1"].mean()) * 100, 1) if len(det_races) else None),
            "det_races": int(len(det_races)),
        },
        # 会場はイン率の高い順（堅い→荒れる）
        "venues": to_records(by_venue, "Venue", "venue"),
        # レース番号は 1R→12R
        "races": to_records(by_race.sort_values("R"), "R", "r"),
    }
    dash_path = os.path.join(DATA, "boat_tendency.json")
    with open(dash_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"ダッシュボード用JSON出力: {dash_path}")


if __name__ == "__main__":
    main()
