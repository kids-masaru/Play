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
from pathlib import Path

from codex_learning import (
    LEARNING_STRATEGY_VERSION,
    build_model_learning_context,
    learning_context_for_prompt,
    save_learning_context,
)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("[ERROR] 環境変数 GEMINI_API_KEY が未設定です")
    print("       credentials.env に GEMINI_API_KEY=AIza... を追加してください")
    sys.exit(1)

import google.generativeai as genai
genai.configure(api_key=API_KEY)

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")
RACE_INFO_JSON = os.path.join(DATA_DIR, "daily_race_info.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "daily_gemini_predictions.csv")
LEARNING_JSON = Path(DATA_DIR) / "gemini_learning_summary.json"

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


def format_race(race, learning_context=None):
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
    prompt = PROMPT_TEMPLATE.format(
        venue=race["venue"], r=race["r"],
        weather=race.get("weather") or "-",
        wind_dir=race.get("wind_dir") or "-",
        wind_speed=race.get("wind_speed") or "-",
        wave=race.get("wave") or "-",
        water_temp=race.get("water_temp") or "-",
        boats_text=boats_text,
        odds_text=odds_text,
    )
    if learning_context:
        prompt += """

【確定済み履歴からの学習材料】
以下は予測日より前の結果だけで作成されています。model_feedbackはGemini自身の
過去予測だけです。サンプル数を確認し、短期の外れへ過剰反応せず、今回のレース
情報を優先してください。他モデルの予測は含まれていません。
""" + json.dumps(learning_context, ensure_ascii=False, separators=(",", ":"))
    return prompt


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
    try:
        learning_context = build_model_learning_context(
            Path(DATA_DIR), str(info.get("date", "")), races, "gemini"
        )
        save_learning_context(LEARNING_JSON, learning_context)
    except Exception as e:
        # 学習材料の一時的不備でGemini予測そのものを止めない。
        print(f"[WARN] Gemini学習情報を生成できません: {type(e).__name__}: {e}")
        learning_context = {
            "target_date": str(info.get("date", "")),
            "model_key": "gemini",
            "historical_results_used": 0,
            "model_feedback": {"settled_count": 0, "status": "unavailable"},
            "races": {},
        }
    feedback_count = learning_context.get("model_feedback", {}).get("settled_count", 0)
    print(f"学習情報: Gemini結果確定 {feedback_count} レース")
    results = []
    t_overall = time.time()

    for i, race in enumerate(races, 1):
        rid = race["race_id"]
        print(f"\n[{i}/{len(races)}] {race['venue']} {race['r']}R", flush=True)
        prompt_learning = learning_context_for_prompt(learning_context, {str(rid)})
        prompt = format_race(race, prompt_learning)
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
            "Strategy_Gemini": LEARNING_STRATEGY_VERSION,
            "LearningHistoryCount": learning_context.get("historical_results_used", 0),
            "LearningGeminiSettledCount": feedback_count,
        })
        time.sleep(SLEEP_BETWEEN_CALLS)

    new_df = pd.DataFrame(results)
    # --- 永続化（追記式）---
    # 旧実装は毎回 OUTPUT_CSV を当日分だけで上書きしていたため、決着前に翌日分へ
    # 上書きされ Gemini の履歴が貯まらなかった（履歴で Gemini が常に "-" になる原因）。
    # 既存CSVを読み、今回予測した RaceID だけ差し替えて過去分は保持する upsert に変更。
    if os.path.exists(OUTPUT_CSV):
        try:
            old = pd.read_csv(OUTPUT_CSV)
            if "RaceID" in old.columns and len(new_df):
                old = old[~old["RaceID"].astype(str).isin(new_df["RaceID"].astype(str))]
            combined = pd.concat([old, new_df], ignore_index=True)
        except Exception as e:
            print(f"  [WARN] 既存CSV読み込み失敗のため新規分のみ保存: {type(e).__name__}: {e}")
            combined = new_df
    else:
        combined = new_df
    combined.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"\n=== 完了 ({time.time()-t_overall:.1f}s) ===")
    print(f"出力: {OUTPUT_CSV} (今回 {len(results)} レース / 累計 {len(combined)} レース)")
    print(f"今回予測あり: {sum(1 for r in results if r['Stakes_Gemini'])} レース")


if __name__ == "__main__":
    main()
