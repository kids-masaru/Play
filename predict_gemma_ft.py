"""学習版Gemma (gemma-boat:1b) で当日レースを予測 → daily_gemma_predictions.csv に保存。(T13)

入力: dashboard/public/daily_data/daily_race_info.json
出力: dashboard/public/daily_data/daily_gemma_predictions.csv (追記式=履歴を蓄積)

学習版Gemma = gemma_finetune/ で QLoRA 微調整し Ollama に登録したモデル。
既存の Det/LLM(gemma4:e2b) や Gemini と「予測対戦」で比較するための4者目→5者目。

必要: ローカル Ollama が起動し `gemma-boat:1b` が登録済みであること。
      (未登録/未起動なら警告して exit。Det/LLM/Gemini の公開は止めない設計)
"""
import os
import sys
import io
import json
import time
import re
import argparse
import requests
import pandas as pd

# Windows cmd の stdout が cp932 でも日本語/絵文字で落ちないよう UTF-8 化
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")
RACE_INFO_JSON = os.path.join(DATA_DIR, "daily_race_info.json")
OUTPUT_CSV = os.path.join(DATA_DIR, "daily_gemma_predictions.csv")

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = os.environ.get("GEMMA_FT_MODEL", "gemma-boat:1b")
SLEEP_BETWEEN_CALLS = 0.3  # ローカルなので軽め

# 学習時の instruction と同じ文言（微調整の効果を素直に出すため揃える）
INSTRUCTION = "次のボートレースを分析し、3連単(1着-2着-3着)の推論と買い目を答えてください。\n\n"


def check_ollama(model):
    """Ollama 起動と対象モデルの登録を確認。NGなら False。"""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code != 200:
            print(f"[ERROR] Ollama 応答エラー (HTTP {resp.status_code})")
            return False
        names = [m.get("name", "") for m in resp.json().get("models", [])]
        if not any(n == model or n.startswith(model) for n in names):
            print(f"[ERROR] '{model}' が Ollama に未登録です。登録済みモデル: {names}")
            return False
        return True
    except Exception as e:
        print(f"[ERROR] Ollama に接続できません: {type(e).__name__}: {e}")
        print("       Ollama を起動してください（Windows: Ollama アプリ）。")
        return False


def call_gemma(prompt, model, max_retries=3):
    """学習版Gemma(Ollama)を呼び出して応答テキストを返す。"""
    for attempt in range(max_retries):
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 400,
                    "stop": ["<end_of_turn>"],
                },
            }, timeout=300)
            if response.status_code == 200:
                return response.json().get("response", "")
            print(f"  [WARN] Ollama応答エラー (HTTP {response.status_code}): {response.text[:200]}")
        except Exception as e:
            print(f"  [WARN] 呼び出し失敗 (試行{attempt+1}): {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
    return ""


def format_race(race):
    """学習データと同じ並び（会場/天候/出走表）で状況テキストを作る。"""
    lines = [f"【会場】{race['venue']} {race['r']}R"]
    lines.append(
        f"【天候】{race.get('weather') or '-'} / 風 {race.get('wind_speed') or '-'} / "
        f"波 {race.get('wave') or '-'} / 水温 {race.get('water_temp') or '-'}"
    )
    lines.append("【出走表】")
    for b in race["boats"]:
        wr = b.get("win_rate")
        wr_str = f"{wr:.2f}" if wr is not None else "-"
        ex = b.get("ex_time")
        ex_str = f"{ex:.2f}" if ex is not None else "-"
        lines.append(
            f"{b['lane']}号艇 {b['name']} ({b.get('rank', '-')}) "
            f"勝率{wr_str} モーター#{b.get('motor_no', '-')} "
            f"体重{b.get('weight', '-')}kg 展示{ex_str}"
        )
    # オッズ(上位8)も渡す。教師データ(build_dataset)とGeminiに合わせ、学習時と同じ入力に揃える。
    odds_top = race.get("odds_top") or []
    if odds_top:
        lines.append("【3連単オッズ(低い順 上位8)】")
        for o in odds_top[:8]:
            try:
                lines.append(f"  {o['combo']}: {float(o['odds']):.1f}倍")
            except (KeyError, TypeError, ValueError):
                continue
    return INSTRUCTION + "\n".join(lines)


def parse_response(text):
    """[推論]/[買い目] を抽出。3連単(重複なし)を最大5点。"""
    reasoning, current = "", None
    picks = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[推論]") or s.startswith("[最終見解]"):
            current = "reason"; continue
        if s.startswith("[買い目]"):
            current = "picks"; continue
        if current == "reason" and s:
            reasoning += s + "\n"
        # 買い目はどのセクションでも拾う（モデルが見出しを省くことがあるため）
        for m in re.findall(r"[1-6]-[1-6]-[1-6]", s):
            a, b, c = m.split("-")
            if len({a, b, c}) == 3 and m not in picks:
                picks.append(m)
    return {"reasoning": reasoning.strip(), "picks": picks[:5]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=MODEL_NAME, help="Ollamaモデル名 (例 gemma-boat:1b / gemma-boat-claude:1b)")
    ap.add_argument("--out", default="daily_gemma_predictions.csv", help="出力CSV(DATA_DIR相対 or 絶対)")
    ap.add_argument("--tag", default="GemmaFT", help="CSV列サフィックス (Prediction_<tag> 等)")
    args = ap.parse_args()
    model, tag = args.model, args.tag
    out_csv = args.out if os.path.isabs(args.out) else os.path.join(DATA_DIR, args.out)

    if not check_ollama(model):
        sys.exit(1)

    with open(RACE_INFO_JSON, "r", encoding="utf-8") as f:
        info = json.load(f)
    races = info["races"]
    print(f"=== 学習版Gemma予測 ({model}) ===")
    print(f"対象日: {info['date']} / レース数: {len(races)}")

    results = []
    t_overall = time.time()
    for i, race in enumerate(races, 1):
        rid = race["race_id"]
        print(f"\n[{i}/{len(races)}] {race['venue']} {race['r']}R", flush=True)
        prompt = format_race(race)
        t0 = time.time()
        text = call_gemma(prompt, model)
        parsed = parse_response(text)
        print(f"  ({time.time()-t0:.1f}s) {len(parsed['picks'])} 点: {parsed['picks'][:5]}")

        stakes_str = ", ".join(f"{p}:100" for p in parsed["picks"][:5])
        results.append({
            "RaceID": rid,
            "Date": race["date"],
            "Venue": race["venue"],
            "R": race["r"],
            f"Prediction_{tag}": parsed["reasoning"][:1500],
            f"Log_{tag}": text.strip()[:2500],
            f"Stakes_{tag}": stakes_str,
        })
        time.sleep(SLEEP_BETWEEN_CALLS)

    new_df = pd.DataFrame(results)
    # 永続化（追記式 upsert）: 今回の RaceID だけ差し替え、過去分は保持
    if os.path.exists(out_csv):
        try:
            old = pd.read_csv(out_csv)
            if "RaceID" in old.columns and len(new_df):
                old = old[~old["RaceID"].astype(str).isin(new_df["RaceID"].astype(str))]
            combined = pd.concat([old, new_df], ignore_index=True)
        except Exception as e:
            print(f"  [WARN] 既存CSV読み込み失敗のため新規分のみ保存: {type(e).__name__}: {e}")
            combined = new_df
    else:
        combined = new_df
    combined.to_csv(out_csv, index=False, encoding="utf-8")
    print(f"\n=== 完了 ({time.time()-t_overall:.1f}s) ===")
    print(f"出力: {out_csv} (今回 {len(results)} レース / 累計 {len(combined)} レース)")
    print(f"今回予測あり: {sum(1 for r in results if r[f'Stakes_{tag}'])} レース")


if __name__ == "__main__":
    main()
