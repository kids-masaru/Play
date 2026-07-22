"""教師データ構築: 過去レースの状況 → Gemini が良質な「推論＋買い目」のお手本を生成 → JSONL。(T5)

Gemini が"先生"。各レースの状況（出走表・直前情報・オッズ）と実際の結果を渡し、
「結果が出る前の視点で、状況から読み解いた前向きな分析＋買い目」を書かせる。
（結果を知った上で筋の良い解説を作るが、"結果が出たから"とは書かせない＝予測時に使える形）

入力（past_data/）:
  past_history_results.csv   Date,Venue,R,ID,Result,Payout
  past_race_data.csv         Date,Venue,R,ID,Lane,PlayerID,Name,Motor,Rank,WinRate,Count
  past_raw_beforeinfo.csv    ID,Date,Venue,R,Weather,WindSpeed,WindDir,Wave,WaterTemp,B{n}_Weight/Tilt/ExTime
  past_odds_3t_backfill/<YYYYMMDD>.csv   ID,Date,Venue,R,Combination,Odds

出力:
  gemma_finetune/data/train.jsonl   1行 = {"instruction": 状況, "output": "[推論]...[買い目]..."}

必要: 環境変数 GEMINI_API_KEY（run_build_dataset.bat 経由で credentials.env から展開）

使い方:
  python gemma_finetune/data/build_dataset.py            # 既定 80 レース
  python gemma_finetune/data/build_dataset.py 120        # 件数指定
"""
import os
import sys
import io
import re
import json
import time
import random
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))            # .../Play
PAST = os.path.join(REPO, "past_data")
OUT_JSONL = os.path.join(HERE, "train.jsonl")

RESULTS_CSV = os.path.join(PAST, "past_history_results.csv")
RACE_CSV = os.path.join(PAST, "past_race_data.csv")
BEFORE_CSV = os.path.join(PAST, "past_raw_beforeinfo.csv")
ODDS_DIR = os.path.join(PAST, "past_odds_3t_backfill")

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
SLEEP = 1.5            # API レート配慮
ODDS_TOP = 8          # オッズ上位の表示数

TEACHER_PROMPT = """あなたはボートレース予想の超一流アナリストです。
以下のレースを「結果が出る前の視点」で分析し、買い目を導く解説を書いてください。

参考（学習用の内部情報・本文には結果が出たとは書かないこと）:
  このレースの実際の結果は {result}（払戻 {payout}円）でした。
  この結果に整合する筋の良い分析を、あくまで状況から読み解いた前向きな分析として書いてください。

【レース状況】
{situation}

次のフォーマットで日本語で回答してください:

[推論]
（3-5行。コース有利・各選手の地力(勝率/級別)・モーター・展示・オッズの妙味から、軸とどう流すか）

[買い目]
（3連単を3-5点、1行1点で「1-2-3」形式のみ。実際に来た {result} の筋を自然に推奨へ含める）
"""


def parse_combo(s):
    m = re.match(r"\s*(\d)\s*-\s*(\d)\s*-\s*(\d)", str(s))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def load_inputs():
    res = pd.read_csv(RESULTS_CSV, dtype=str).fillna("")
    race = pd.read_csv(RACE_CSV, dtype=str).fillna("")
    before = pd.read_csv(BEFORE_CSV, dtype=str).fillna("")
    return res, race, before


def odds_for_date(yyyymmdd, _cache={}):
    """その日のオッズCSVを読み（キャッシュ）、ID→[(combo,odds)] 上位を返す関数を提供。"""
    if yyyymmdd not in _cache:
        path = os.path.join(ODDS_DIR, f"{yyyymmdd}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path, dtype=str).fillna("")
            df["Odds_f"] = pd.to_numeric(df["Odds"], errors="coerce")
            _cache[yyyymmdd] = df
        else:
            _cache[yyyymmdd] = None
    return _cache[yyyymmdd]


def build_situation(rid, race_df, before_df, odds_df):
    """1レースの状況テキストを組み立てる。失敗時 None。"""
    boats = race_df[race_df["ID"] == rid].copy()
    if boats.empty:
        return None
    boats["Lane_i"] = pd.to_numeric(boats["Lane"], errors="coerce")
    boats = boats.sort_values("Lane_i")

    venue = boats.iloc[0]["Venue"]
    r = boats.iloc[0]["R"]

    bi = before_df[before_df["ID"] == rid]
    bi = bi.iloc[0] if not bi.empty else None

    lines = [f"【会場】{venue} {r}R"]
    if bi is not None:
        lines.append(
            f"【天候】{bi.get('Weather','-')} / 風 {bi.get('WindDir','-')} {bi.get('WindSpeed','-')} "
            f"/ 波 {bi.get('Wave','-')} / 水温 {bi.get('WaterTemp','-')}"
        )
    lines.append("【出走表】")
    for _, b in boats.iterrows():
        lane = b.get("Lane", "?")
        ex = bi.get(f"B{lane}_ExTime", "") if bi is not None else ""
        wt = bi.get(f"B{lane}_Weight", "") if bi is not None else ""
        lines.append(
            f"{lane}号艇 {b.get('Name','')} ({b.get('Rank','-')}) "
            f"勝率{b.get('WinRate','-')} モーター#{b.get('Motor','-')}"
            + (f" 体重{wt}" if wt else "")
            + (f" 展示{ex}" if ex else "")
        )

    if odds_df is not None:
        o = odds_df[odds_df["ID"] == rid].dropna(subset=["Odds_f"]).sort_values("Odds_f")
        if not o.empty:
            lines.append(f"【3連単オッズ(低い順 上位{ODDS_TOP})】")
            for _, row in o.head(ODDS_TOP).iterrows():
                lines.append(f"  {row['Combination']}: {row['Odds_f']:.1f}倍")
    return "\n".join(lines)


def parse_teacher(text):
    """Geminiの応答から [推論] と [買い目] を取り出し、お手本テキストに整形。"""
    reasoning, picks = "", []
    cur = None
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[推論]"):
            cur = "r"; continue
        if s.startswith("[買い目]"):
            cur = "p"; continue
        if not s:
            continue
        if cur == "r":
            reasoning += s + "\n"
        elif cur == "p":
            for m in re.findall(r"[1-6]-[1-6]-[1-6]", s):
                a, b, c = m.split("-")
                if len({a, b, c}) == 3 and m not in picks:
                    picks.append(m)
    reasoning = reasoning.strip()
    picks = picks[:5]
    if not reasoning or not picks:
        return None
    return f"[推論]\n{reasoning}\n\n[買い目]\n" + "\n".join(picks)


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    n_target = int(args[0]) if args else 80

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY が未設定です。run_build_dataset.bat 経由で実行してください。")
        return
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODEL_NAME)

    print(f"=== 教師データ構築 ({MODEL_NAME}) 目標 {n_target} 件 ===")
    res, race, before = load_inputs()

    # 結果ありレースを新しい順に。ID先頭8桁(YYYYMMDD)でオッズ有無を確認しつつ選ぶ
    res = res[res["Result"].astype(str).str.strip() != ""].copy()
    res = res.sort_values("Date", ascending=False)

    written = 0
    seen = set()
    with open(OUT_JSONL, "w", encoding="utf-8") as fout:
        for _, row in res.iterrows():
            if written >= n_target:
                break
            rid = row["ID"]
            if rid in seen:
                continue
            seen.add(rid)
            combo = parse_combo(row["Result"])
            if not combo:
                continue
            ymd = str(rid).split("_")[0]
            if not re.fullmatch(r"\d{8}", ymd):
                continue
            odds_df = odds_for_date(ymd)
            situation = build_situation(rid, race, before, odds_df)
            if not situation:
                continue

            prompt = TEACHER_PROMPT.format(result=combo, payout=row.get("Payout", "?"),
                                           situation=situation)
            try:
                resp = model.generate_content(prompt)
                out = parse_teacher(resp.text)
            except Exception as e:
                print(f"  [WARN] {rid} 生成失敗: {type(e).__name__}: {e}")
                out = None
            if not out:
                continue

            fout.write(json.dumps({"instruction": situation, "output": out},
                                  ensure_ascii=False) + "\n")
            written += 1
            if written % 10 == 0:
                print(f"  {written}/{n_target} 件 生成済み（最新: {rid} 結果{combo}）")
            time.sleep(SLEEP)

    print(f"\n完了: {OUT_JSONL} に {written} 件 書き出し")
    if written < n_target:
        print(f"（目標{n_target}に届かず。素材不足/生成失敗の可能性。件数を減らすか素材を確認）")


if __name__ == "__main__":
    main()
