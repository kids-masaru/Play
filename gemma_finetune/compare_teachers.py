"""Gemini先生版(gemma-boat:1b) vs Claude先生版(gemma-boat-claude:1b) を同一レースで比較。

学習に使っていない「今日のレース」(daily_race_info.json)で、両モデルの [推論]/[買い目] を並べる。
"""
import os
import sys
import io
import json
import requests

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RACE_INFO = os.path.join(ROOT, "dashboard", "public", "daily_data", "daily_race_info.json")
OLLAMA = "http://localhost:11434/api/generate"
INSTRUCTION = "次のボートレースを分析し、3連単(1着-2着-3着)の推論と買い目を答えてください。\n\n"
MODELS = [("Gemini先生版", "gemma-boat:1b"), ("Claude先生版", "gemma-boat-claude:1b")]
N = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def format_race(race):
    lines = [f"【会場】{race['venue']} {race['r']}R"]
    lines.append(f"【天候】{race.get('weather') or '-'} / 風 {race.get('wind_speed') or '-'} / "
                 f"波 {race.get('wave') or '-'} / 水温 {race.get('water_temp') or '-'}")
    lines.append("【出走表】")
    for b in race["boats"]:
        wr = b.get("win_rate"); ex = b.get("ex_time")
        wr_s = f"{wr:.2f}" if wr is not None else "-"
        ex_s = f"{ex:.2f}" if ex is not None else "-"
        lines.append(f"{b['lane']}号艇 {b['name']} ({b.get('rank','-')}) "
                     f"勝率{wr_s} モーター#{b.get('motor_no','-')} "
                     f"体重{b.get('weight','-')}kg 展示{ex_s}")
    odds_top = race.get("odds_top") or []
    if odds_top:
        lines.append("【3連単オッズ(低い順 上位8)】")
        for o in odds_top[:8]:
            try:
                lines.append(f"  {o['combo']}: {float(o['odds']):.1f}倍")
            except (KeyError, TypeError, ValueError):
                continue
    return INSTRUCTION + "\n".join(lines)


def gen(model, prompt):
    try:
        r = requests.post(OLLAMA, json={"model": model, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.7, "num_predict": 400, "stop": ["<end_of_turn>"]}},
                          timeout=300)
        return r.json().get("response", "").strip() if r.status_code == 200 else f"[HTTP {r.status_code}]"
    except Exception as e:
        return f"[ERR {type(e).__name__}: {e}]"


def main():
    info = json.load(open(RACE_INFO, encoding="utf-8"))
    races = info["races"][:N]
    print(f"=== 先生対決: {info['date']} の {len(races)}レース（未学習）===\n")
    for race in races:
        prompt = format_race(race)
        head = f"{race['venue']} {race['r']}R"
        print("=" * 64)
        print(f"■ {head}")
        print("=" * 64)
        for label, model in MODELS:
            print(f"\n--- [{label}] {model} ---")
            print(gen(model, prompt)[:700])
        print()


if __name__ == "__main__":
    main()
