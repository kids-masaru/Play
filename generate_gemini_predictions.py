"""Gemini API で当日レースを予測 → daily_gemini_predictions.csv に保存。

入力: dashboard/public/daily_data/daily_race_info.json
出力: dashboard/public/daily_data/daily_gemini_predictions.csv

必要: 環境変数 GEMINI_API_KEY (credentials.env で設定)
"""
import os
import sys
import io
import json
import time
import re
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] 環境変数 GEMINI_API_KEY が未設定です")
    print("       credentials.env に GEMINI_API_KEY=AIza... を追加してください")
    sys.exit(1)

import google.generativeai as genai
genai.configure(api_key=API_KEY)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")
RACE_INFO_JSON = os.path.join(DATA_DIR, "daily_race_info.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "daily_gemini_predictions.csv")

SLEEP_BETWEEN_CALLS = 1.5  # rate limit余裕

PROMPT_TEMPLATE = """あなたはボートレース予想のプロです。
以下のレース情報を分析し、まず「買う価値（妙味）があるレースか」を判断してください。
オッズに対して期待値が見込めない（本命が堅すぎてオッズに妙味がない／荒れすぎて読めない等）と
判断した場合は、無理に賭けず「見送り」にしてください。"買わない判断"もプロの腕のうちです。

【会場】{venue} {r}R
【天候】{weather} / 風: {wind_dir} {wind_speed} / 波: {wave} / 水温: {water_temp}

【出走表】
{boats_text}
【3連単オッズ(低い順 上位)】
{odds_text}
以下のフォーマットで必ず回答してください。

[思考]
（推論プロセス、3-5行で。インコース有利か、各艇の調子、オッズに妙味があるか）

[最終見解]
（1-2行で結論。買うなら軸と理由、見送るならその理由）

[買い目]
（妙味があれば3連単を3-5点、1行1点で「1-2-3」形式のみ。
　買う価値がないと判断したら「見送り」とだけ書き、買い目は出さないこと）
"""


def format_race(race):
    boats_text = ""
    for b in race["boats"]:
        win_rate = b.get('win_rate')
        wr_str = f"{win_rate:.2f}" if win_rate is not None else "-"
        boats_text += (
            f"{b['lane']}号艇: {b['name']} ({b.get('rank', '-')}) "
            f"勝率{wr_str} モーター#{b.get('motor_no', '-')}\n"
        )
    odds_text = ""
    for o in race["odds_top"][:10]:
        odds_text += f"  {o['combo']}: {o['odds']:.1f}倍\n"
    return PROMPT_TEMPLATE.format(
        venue=race["venue"], r=race["r"],
        weather=race.get("weather") or "-",
        wind_dir=race.get("wind_dir") or "-",
        wind_speed=race.get("wind_speed") or "-",
        wave=race.get("wave") or "-",
        water_temp=race.get("water_temp") or "-",
        boats_text=boats_text,
        odds_text=odds_text,
    )


def parse_response(text):
    sections = {"thought": "", "verdict": "", "picks": []}
    current = None
    skip = False  # 「見送り」判定（買う価値なし）
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("[思考]"):
            current = "thought"; continue
        if stripped.startswith("[最終見解]"):
            current = "verdict"; continue
        if stripped.startswith("[買い目]"):
            current = "picks"; continue
        if not stripped:
            if current in ("thought", "verdict"):
                sections[current] += "\n"
            continue
        if current == "thought":
            sections["thought"] += stripped + "\n"
        elif current == "verdict":
            sections["verdict"] += stripped + "\n"
        elif current == "picks":
            if "見送り" in stripped:
                skip = True
                continue
            for m in re.findall(r"[1-6]-[1-6]-[1-6]", stripped):
                # 同じ艇番号重複は除外
                a, b, c = m.split("-")
                if len({a, b, c}) == 3:
                    sections["picks"].append(m)
    if skip:
        # 見送り宣言があれば買い目は出さない（妙味なしレース）
        sections["picks"] = []
    # 重複除去・上限5
    seen = set()
    unique = []
    for p in sections["picks"]:
        if p not in seen:
            seen.add(p)
            unique.append(p)
        if len(unique) >= 5:
            break
    sections["picks"] = unique
    return sections


def main():
    with open(RACE_INFO_JSON, "r", encoding="utf-8") as f:
        info = json.load(f)

    races = info["races"]
    print(f"=== Gemini予測 ({MODEL_NAME}) ===")
    print(f"対象日: {info['date']}")
    print(f"レース数: {len(races)}")

    model = genai.GenerativeModel(MODEL_NAME)
    results = []
    t_overall = time.time()

    for i, race in enumerate(races, 1):
        rid = race["race_id"]
        print(f"\n[{i}/{len(races)}] {race['venue']} {race['r']}R", flush=True)
        prompt = format_race(race)
        try:
            t0 = time.time()
            response = model.generate_content(prompt)
            elapsed = time.time() - t0
            text = response.text
            parsed = parse_response(text)
            print(f"  ({elapsed:.1f}s) {len(parsed['picks'])} 点: {parsed['picks'][:5]}")
        except Exception as e:
            print(f"  [ERR] {type(e).__name__}: {e}")
            text = ""
            parsed = {"thought": "", "verdict": "", "picks": []}

        stakes_str = ", ".join(f"{p}:100" for p in parsed["picks"][:5])
        results.append({
            "RaceID": rid,
            "Date": race["date"],
            "Venue": race["venue"],
            "R": race["r"],
            "Prediction_Gemini": parsed["verdict"].strip()[:1500],
            "Log_Gemini": parsed["thought"].strip()[:2500],
            "Stakes_Gemini": stakes_str,
        })
        time.sleep(SLEEP_BETWEEN_CALLS)

    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"\n=== 完了 ({time.time()-t_overall:.1f}s) ===")
    print(f"出力: {OUTPUT_CSV} ({len(results)} レース)")
    print(f"予測あり: {sum(1 for r in results if r['Stakes_Gemini'])} レース")


if __name__ == "__main__":
    main()
