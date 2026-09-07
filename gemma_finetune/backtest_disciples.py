# -*- coding: utf-8 -*-
"""弟子LLMの一括バックテスト（提案A）。

学習期間外（2026-08-01以降）のレースからランダムサンプルし、
各弟子モデルに本番と同一形式・同一パラメータで予測させ、
実結果と突き合わせて 的中率 / ROI / 最大ドローダウン を算出する。

賭け方は本番Stakes方式と同じ「各買い目に100円」。
使い方:
  python gemma_finetune/backtest_disciples.py [レース数=120]
"""
import os
import re
import io
import sys
import json
import time
import random
import requests
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DD = os.path.join(ROOT, "daily_data")
OLLAMA = "http://localhost:11434/api/generate"
INSTRUCTION = "次のボートレースを分析し、3連単(1着-2着-3着)の推論と買い目を答えてください。\n\n"
START_DATE = "2026-08-01"   # 全教師データ(〜7月)より後 = 未学習期間
SEED = 42
N = int(sys.argv[1]) if len(sys.argv) > 1 else 120

# (表示名, モデル名, stopトークン)
MODELS = [
    ("Gemma/Gemini", "gemma-boat:1b", "<end_of_turn>"),
    ("Gemma/Claude", "gemma-boat-claude:1b", "<end_of_turn>"),
    ("Gemma/GrokX", "gemma-boat-grok-x:1b", "<end_of_turn>"),
    ("Qwen/Claude", "qwen-boat-claude:1.7b", "<|im_end|>"),
    ("Qwen/GrokX_v2", "qwen-boat-grok-x-v2:1.7b", "<|im_end|>"),
]


def parse_picks(text):
    """本番 predict_gemma_ft.parse_response と同等: 3連単(重複なし)を最大5点。"""
    picks = []
    for line in str(text).splitlines():
        m = re.match(r"\s*(\d)\s*-\s*(\d)\s*-\s*(\d)\s*$", line)
        if m:
            a, b, c = m.group(1), m.group(2), m.group(3)
            combo = f"{a}-{b}-{c}"
            if len({a, b, c}) == 3 and combo not in picks:
                picks.append(combo)
    return picks[:5]


def gen(model, prompt, stop):
    """本番と同一パラメータで生成。"""
    try:
        r = requests.post(OLLAMA, json={
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.7, "num_predict": 400, "stop": [stop]},
        }, timeout=300)
        return r.json().get("response", "") if r.status_code == 200 else ""
    except Exception as e:
        print(f"  [WARN] {model}: {type(e).__name__}", flush=True)
        return ""


def load_races():
    """8月以降の結果からNレースをサンプルし、プロンプト材料を揃える。"""
    res = pd.read_csv(os.path.join(DD, "daily_history_results.csv"), dtype=str).fillna("")
    res = res[(res["Date"] >= START_DATE) & res["Result"].str.match(r"^\d-\d-\d$")]
    res["Payout_i"] = pd.to_numeric(res["Payout"], errors="coerce")
    res = res.dropna(subset=["Payout_i"])
    random.seed(SEED)
    ids = sorted(random.sample(list(res["ID"]), min(N, len(res))))
    res = res[res["ID"].isin(ids)].set_index("ID")

    race = pd.read_csv(os.path.join(DD, "daily_raw_race_data.csv"), dtype=str).fillna("")
    race = race[race["ID"].isin(ids)]
    before = pd.read_csv(os.path.join(DD, "daily_raw_beforeinfo.csv"), dtype=str).fillna("")
    before = before[before["ID"].isin(ids)].set_index("ID")

    # オッズ(150MB)はチャンク読みで対象IDだけ抽出
    odds_rows = []
    for chunk in pd.read_csv(os.path.join(DD, "daily_odds_3t.csv"), dtype=str, chunksize=500_000):
        odds_rows.append(chunk[chunk["ID"].isin(ids)])
    odds = pd.concat(odds_rows)
    odds["Odds_f"] = pd.to_numeric(odds["Odds"], errors="coerce")

    races = []
    for rid in ids:
        boats = race[race["ID"] == rid].copy()
        if len(boats) != 6:
            continue
        boats["Lane_i"] = pd.to_numeric(boats["Lane"], errors="coerce")
        boats = boats.sort_values("Lane_i")
        bi = before.loc[rid] if rid in before.index else None

        lines = [f"【会場】{boats.iloc[0]['Venue']} {boats.iloc[0]['R']}R"]
        if bi is not None:
            lines.append(f"【天候】{bi.get('Weather','-')} / 風 {bi.get('WindSpeed','-')} / "
                         f"波 {bi.get('Wave','-')} / 水温 {bi.get('WaterTemp','-')}")
        lines.append("【出走表】")
        for _, b in boats.iterrows():
            lane = b["Lane"]
            wt = bi.get(f"B{lane}_Weight", "") if bi is not None else ""
            ex = bi.get(f"B{lane}_ExTime", "") if bi is not None else ""
            lines.append(f"{lane}号艇 {b['Name']} ({b['Rank']}) 勝率{b['WinRate']} モーター#{b['Motor']}"
                         + (f" 体重{wt}kg" if wt else "") + (f" 展示{ex}" if ex else ""))
        o = odds[odds["ID"] == rid].dropna(subset=["Odds_f"]).sort_values("Odds_f")
        if not o.empty:
            lines.append("【3連単オッズ(低い順 上位8)】")
            for _, row in o.head(8).iterrows():
                lines.append(f"  {row['Combination']}: {row['Odds_f']:.1f}倍")

        races.append({
            "id": rid, "date": res.loc[rid, "Date"],
            "result": res.loc[rid, "Result"], "payout": float(res.loc[rid, "Payout_i"]),
            "prompt": INSTRUCTION + "\n".join(lines),
        })
    return races


def max_drawdown(pnl_series):
    """累積損益系列から最大ドローダウン(円)を返す。"""
    peak, mdd, cum = 0.0, 0.0, 0.0
    for p in pnl_series:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def main():
    races = load_races()
    print(f"=== 弟子バックテスト: {len(races)}レース ({START_DATE}以降, seed={SEED}) ===", flush=True)

    rows = []
    summary = {}
    for label, model, stop in MODELS:   # モデル外側ループ=ロード切替を最小化
        t0 = time.time()
        print(f"\n--- {label} ({model}) 推論中...", flush=True)
        for i, rc in enumerate(races):
            picks = parse_picks(gen(model, rc["prompt"], stop))
            inv = 100 * len(picks)
            ret = rc["payout"] if rc["result"] in picks else 0.0
            rows.append({"model": label, "id": rc["id"], "date": rc["date"],
                         "result": rc["result"], "payout": rc["payout"],
                         "picks": " ".join(picks), "n_picks": len(picks),
                         "hit": int(rc["result"] in picks), "inv": inv, "ret": ret})
            if (i + 1) % 20 == 0:
                print(f"  {i+1}/{len(races)}", flush=True)

        df = pd.DataFrame([r for r in rows if r["model"] == label]).sort_values("date")
        n_pred = int((df["n_picks"] > 0).sum())
        inv, ret = df["inv"].sum(), df["ret"].sum()
        summary[label] = {
            "races": len(df), "predicted": n_pred,
            "avg_picks": round(float(df["n_picks"].mean()), 2),
            "hits": int(df["hit"].sum()),
            "hit_rate_pct": round(df["hit"].mean() * 100, 1),
            "invest": int(inv), "return": int(ret),
            "roi_pct": round(ret / inv * 100, 1) if inv else 0.0,
            "pnl": int(ret - inv),
            "max_drawdown": int(max_drawdown((df["ret"] - df["inv"]).tolist())),
            "minutes": round((time.time() - t0) / 60, 1),
        }
        s = summary[label]
        print(f"  完了({s['minutes']}分) 的中{s['hits']}/{s['races']} ({s['hit_rate_pct']}%) "
              f"ROI {s['roi_pct']}% 損益{s['pnl']:+,}円 最大DD{s['max_drawdown']:,}円", flush=True)

    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    pd.DataFrame(rows).to_csv(os.path.join(ROOT, "reports", "disciple_backtest_races.csv"),
                              index=False, encoding="utf-8-sig")
    with open(os.path.join(ROOT, "reports", "disciple_backtest_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n=== サマリー ===", flush=True)
    print(f"{'モデル':<16}{'的中率':>8}{'ROI':>8}{'損益':>12}{'最大DD':>10}")
    for label, s in summary.items():
        print(f"{label:<16}{s['hit_rate_pct']:>7}%{s['roi_pct']:>7}%{s['pnl']:>+11,}円{s['max_drawdown']:>9,}円")
    print("\n保存: reports/disciple_backtest_races.csv / disciple_backtest_summary.json", flush=True)


if __name__ == "__main__":
    main()
