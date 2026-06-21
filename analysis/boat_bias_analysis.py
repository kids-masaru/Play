# -*- coding: utf-8 -*-
"""
ボートレース Det予測の「偏り」集計スクリプト
------------------------------------------------------------
目的: Detモデル(LightGBM)の買い目が「どの会場・どのレース番号で
      よく当たっているか / 収支が良いか」を集計し、masaru さんの
      肌感（例: 12Rがよく当たる気がする）が本物かノイズかを検証する。

入力(daily_data 配下):
  - daily_predictions.csv     : RaceID, Venue, R, Stakes_Det(買い目 JSON)
  - daily_history_results.csv : ID(=RaceID), Result(例 "3-4-6"), Payout(100円あたり)

集計の定義:
  - 対象 = Detが実際に買い目を出したレース(Stakes_Det が空でない)
  - 的中 = 実結果の3連単が買い目に含まれる
  - 投資 = その買い目の賭け金合計
  - 払戻 = 的中時、当たった買い目の賭け金 × (Payout/100)
  - ROI  = 払戻合計 / 投資合計 × 100 (%)
出力:
  - コンソールに「会場別」「レース番号別」サマリ
  - analysis/out/boat_bias_by_venue.csv / boat_bias_by_race.csv
"""
import json
import os
import sys
import pandas as pd

# Windows cmd の cp932 で絵文字等が出ても落ちないように
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(BASE, "..", "dashboard", "public", "daily_data"))
OUT = os.path.join(BASE, "out")
os.makedirs(OUT, exist_ok=True)


def norm_result(s):
    """ '3-4-6' -> '346' （3連単の順序を保持） """
    if not isinstance(s, str):
        return None
    return s.replace("-", "").strip()


def parse_stakes(s):
    """ Stakes_Det(JSON文字列) -> {買い目:賭け金} dict。空/壊れは {} """
    if not isinstance(s, str) or not s.strip():
        return {}
    try:
        d = json.loads(s)
        # キーを文字列化(数値キー対策)
        return {str(k): float(v) for k, v in d.items()}
    except Exception:
        return {}


def main():
    preds = pd.read_csv(os.path.join(DATA, "daily_predictions.csv"))
    res = pd.read_csv(os.path.join(DATA, "daily_history_results.csv"))

    # 結果を RaceID で引けるように辞書化
    res = res.dropna(subset=["ID", "Result"])
    res_map = {}
    for _, row in res.iterrows():
        res_map[str(row["ID"])] = (norm_result(row["Result"]), row.get("Payout"))

    rows = []
    for _, p in preds.iterrows():
        rid = str(p["RaceID"])
        stakes = parse_stakes(p.get("Stakes_Det"))
        if not stakes:
            continue  # Detが買っていないレースは対象外
        if rid not in res_map:
            continue  # 結果未確定は対象外
        result, payout = res_map[rid]
        if not result:
            continue
        inv = sum(stakes.values())
        hit = result in stakes
        ret = 0.0
        if hit and pd.notna(payout):
            ret = float(payout) * (stakes[result] / 100.0)
        rows.append({
            "Venue": p["Venue"],
            "R": int(p["R"]) if pd.notna(p["R"]) else None,
            "hit": int(hit),
            "inv": inv,
            "ret": ret,
        })

    if not rows:
        print("対象レースが0件でした。CSVの中身を確認してください。")
        return

    df = pd.DataFrame(rows)
    n = len(df)
    print(f"=== 全体 ===")
    print(f"対象レース数(Detが買い目を出し結果確定): {n}")
    print(f"的中率: {df['hit'].mean()*100:.1f}%  ({df['hit'].sum()}/{n})")
    print(f"投資合計: ¥{df['inv'].sum():,.0f}  払戻合計: ¥{df['ret'].sum():,.0f}")
    print(f"ROI: {df['ret'].sum()/df['inv'].sum()*100:.1f}%")
    print()

    def summarize(by):
        g = df.groupby(by).agg(
            races=("hit", "size"),
            hits=("hit", "sum"),
            inv=("inv", "sum"),
            ret=("ret", "sum"),
        ).reset_index()
        g["hit_rate(%)"] = (g["hits"] / g["races"] * 100).round(1)
        g["ROI(%)"] = (g["ret"] / g["inv"] * 100).round(1)
        return g

    by_venue = summarize("Venue").sort_values("ROI(%)", ascending=False)
    by_race = summarize("R").sort_values("R")

    pd.set_option("display.unicode.east_asian_width", True)
    print("=== 会場別（ROI降順）===")
    print(by_venue[["Venue", "races", "hits", "hit_rate(%)", "ROI(%)"]].to_string(index=False))
    print()
    print("=== レース番号別（1R〜12R）===")
    print(by_race[["R", "races", "hits", "hit_rate(%)", "ROI(%)"]].to_string(index=False))

    by_venue.to_csv(os.path.join(OUT, "boat_bias_by_venue.csv"), index=False, encoding="utf-8-sig")
    by_race.to_csv(os.path.join(OUT, "boat_bias_by_race.csv"), index=False, encoding="utf-8-sig")
    print()
    print(f"CSV出力: {OUT}\\boat_bias_by_venue.csv / boat_bias_by_race.csv")


if __name__ == "__main__":
    main()
