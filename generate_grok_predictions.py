"""xAI Grok を予測対戦の一参加者として実行する。

XAI_API_KEY が未設定の場合は失敗終了する。朝バッチ側では任意参加者として
扱うため、他の予測・公開処理を止めない。
"""
import json
import os
import re
import sys
import time
import csv
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
RACE_INFO_JSON = DATA_DIR / "daily_race_info.json"
OUTPUT_CSV = DATA_DIR / "daily_grok_predictions.csv"
API_KEY = os.environ.get("XAI_API_KEY")
MODEL_NAME = os.environ.get("GROK_MODEL", "grok-4.5")
API_URL = "https://api.x.ai/v1/chat/completions"


def format_race(race):
    boats = "\n".join(
        f"{b['lane']}号艇 {b['name']} ({b.get('rank', '-')}) 勝率{b.get('win_rate', '-')}, モーター{b.get('motor_no', '-')}"
        for b in race["boats"]
    )
    odds = "\n".join(f"{o['combo']}: {o['odds']}倍" for o in race["odds_top"][:10])
    return f"""あなたはボートレース予想の分析者です。次の事前情報だけを使い、結果は知っている前提にしないでください。
堅実性、選手・モーター、展示・気象、オッズのバランスを判断してください。

会場: {race['venue']} {race['r']}R
天候: {race.get('weather') or '-'} / 風: {race.get('wind_dir') or '-'} {race.get('wind_speed') or '-'} / 波: {race.get('wave') or '-'}
選手:
{boats}
人気オッズ:
{odds}

日本語で「分析」「結論」「買い目」の順に書いてください。買い目は3〜5点、`1-2-3`形式で列挙してください。"""


def call_grok(prompt):
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [{"role": "user", "content": prompt}],
        "reasoning_effort": "low",
        "temperature": 0.3,
    }).encode("utf-8")
    req = request.Request(API_URL, data=payload, headers={
        "Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json",
    }, method="POST")
    try:
        with request.urlopen(req, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except (error.HTTPError, error.URLError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Grok API error: {exc}") from exc


def picks_from(text):
    picks, seen = [], set()
    for item in re.findall(r"[1-6]-[1-6]-[1-6]", text):
        if len(set(item.split("-"))) == 3 and item not in seen:
            seen.add(item)
            picks.append(item)
        if len(picks) == 5:
            break
    return picks


def main():
    if not API_KEY:
        print("[ERROR] XAI_API_KEY が未設定です。")
        return 1
    with RACE_INFO_JSON.open(encoding="utf-8") as f:
        info = json.load(f)
    rows = []
    successful = 0
    for index, race in enumerate(info["races"], 1):
        try:
            text = call_grok(format_race(race))
            picks = picks_from(text)
            successful += 1
            print(f"[{index}/{len(info['races'])}] {race['venue']} {race['r']}R: {picks}")
        except RuntimeError as exc:
            print(f"[WARN] {race['race_id']}: {exc}")
            text, picks = "", []
        rows.append({"RaceID": race["race_id"], "Date": race["date"], "Venue": race["venue"], "R": race["r"],
                     "Prediction_Grok": text[:1500], "Log_Grok": text[:2500],
                     "Stakes_Grok": ", ".join(f"{pick}:100" for pick in picks)})
        time.sleep(1)
    existing = []
    if OUTPUT_CSV.exists():
        with OUTPUT_CSV.open("r", encoding="utf-8", newline="") as f:
            existing = list(csv.DictReader(f))
    new_ids = {str(row["RaceID"]) for row in rows}
    combined = [row for row in existing if str(row.get("RaceID", "")) not in new_ids] + rows
    fields = ["RaceID", "Date", "Venue", "R", "Prediction_Grok", "Log_Grok", "Stakes_Grok"]
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(combined)
    print(f"完了: {OUTPUT_CSV}")
    if successful == 0:
        print("[ERROR] Grok API returned no successful predictions.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
