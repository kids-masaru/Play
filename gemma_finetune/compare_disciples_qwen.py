"""Gemma弟子(Claude先生) vs Qwen弟子(Claude先生) を同一レースで比較。

compare_teachers.py をベースに、モデルをQwen弟子対応にし速度計測を追加した版。
学習に使っていない「今日のレース」(daily_race_info.json)で [推論]/[買い目] を並べる。
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
# (表示名, モデル名, stopトークン)
MODELS = [
    ("Gemma弟子/GrokX先生", "gemma-boat-grok-x:1b", "<end_of_turn>"),
    ("Qwen弟子/GrokX先生v1", "qwen-boat-grok-x:1.7b", "<|im_end|>"),
    ("Qwen弟子/GrokX先生v2", "qwen-boat-grok-x-v2:1.7b", "<|im_end|>"),
]
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


def gen(model, prompt, stop):
    """生成テキストと速度統計(tok/s)を返す"""
    try:
        r = requests.post(OLLAMA, json={"model": model, "prompt": prompt, "stream": False,
                          "options": {"temperature": 0.7, "num_predict": 400, "stop": [stop]}},
                          timeout=300)
        if r.status_code != 200:
            return f"[HTTP {r.status_code}]", None
        j = r.json()
        ec = j.get("eval_count", 0)
        ed = j.get("eval_duration", 1) / 1e9
        tps = ec / ed if ed > 0 else 0
        total = j.get("total_duration", 0) / 1e9
        return j.get("response", "").strip(), f"{ec}tok {tps:.1f}tok/s 合計{total:.1f}s"
    except Exception as e:
        return f"[ERR {type(e).__name__}: {e}]", None


def main():
    info = json.load(open(RACE_INFO, encoding="utf-8"))
    races = info["races"][:N]
    print(f"=== 弟子対決(Claude先生教材): {info['date']} の {len(races)}レース（未学習）===\n")
    for race in races:
        prompt = format_race(race)
        head = f"{race['venue']} {race['r']}R"
        print("=" * 64)
        print(f"■ {head}")
        print("=" * 64)
        for label, model, stop in MODELS:
            text, stat = gen(model, prompt, stop)
            print(f"\n--- [{label}] {model} ({stat}) ---")
            print(text[:700])
        print()


if __name__ == "__main__":
    main()
