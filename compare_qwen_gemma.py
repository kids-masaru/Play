# -*- coding: utf-8 -*-
"""
qwen3.5:4b vs gemma4:e2b 比較検証スクリプト（使い捨て）
本番 predict_with_deepseek.py と同一のプロンプト・パラメータで
予測品質と速度（tok/s）を比較する。
対象レース: 2026-09-07 大村12R（実データ）
"""
import sys
import json
import time
import requests

# Windows cp932 対策
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OLLAMA_URL = "http://localhost:11434/api/generate"
# ラウンド3: 両モデルに同じ「競艇ルール」システムプロンプトを与えてフェア比較
MODELS = ["gemma4:e2b", "qwen3.5:4b"]
THINK_OFF_MODELS = {"qwen3.5:4b"}  # 思考モードOFF対象（Gemmaは非対応のため除外）

# 競艇の基本ルール（前回Qwenが誤解していた点を重点的に明文化）
SYSTEM_RULES = """あなたは競艇（ボートレース）の予想AIです。以下の基本ルールを厳守して分析してください。

【競技の基本】
- 6艇が水面を3周して着順を競う。1〜6号艇があり、原則として艇番＝進入コース。
- 1コース（イン）が圧倒的に有利。全国平均で1コース1着率は約55%。特に大村・徳山・芦屋は「イン天国」と呼ばれ1コース勝率がさらに高い。
- 決まり手は「逃げ」（1コースが先マイ）、「差し」（内側に切れ込む）、「まくり」（外から全速で抜く）、「まくり差し」。陸上競技のような直線追い抜きの概念はない。第1ターンマークでほぼ勝負が決まる。

【データの読み方】
- モーター番号（#65等）は抽選で割り当てられた機番であり、数字の大小は性能と無関係。モーターの良し悪しは2連対率で別途評価する。
- 勝率は平均着順ポイント（0〜10点前後）であり、パーセントではない。6.00以上でA1級相当の強さ。
- 級別は A1 > A2 > B1 > B2 の順に強い。
- 展示タイムは直前の試走タイムで、数値が小さいほど速い。

【買い目】
- 3連単は「1着-2着-3着」を順番通りに当てる（例: 1-2-3）。
- 期待値は的中率とオッズの積で考える。"""

# --- 実データ: 2026-09-07 大村12R ---
race_details = "\n".join([
    "1号艇: 毒島誠 (モーター:61, ランク:A1, 勝率:7.85)",
    "2号艇: 西山貴浩 (モーター:29, ランク:A1, 勝率:7.08)",
    "3号艇: 原田幸哉 (モーター:77, ランク:A1, 勝率:6.66)",
    "4号艇: 丸野一樹 (モーター:31, ランク:A1, 勝率:7.94)",
    "5号艇: 山田康二 (モーター:34, ランク:A1, 勝率:7.96)",
    "6号艇: 上條暢嵩 (モーター:40, ランク:A1, 勝率:7.55)",
])

base_prompt = (
    "以下のボートレースデータから、レース展開と推奨買い目を予想してください。"
    + "\n\n開催地: 大村 第12レース\n出走表:\n" + race_details
)

# 本番コードと同じモック値
lgb_probs_str = "【LightGBM仮算出確率】1号艇: 65%, 2号艇: 15%, 3号艇: 10%, 4号艇: 5%, 5号艇: 3%, 6号艇: 2%"

PROMPTS = {
    "数学者AI": f"あなたはデータ重視の数学者AIです。以下のLightGBMの確率予測とレースデータを元に、最も期待値の高い論理的な予想と理由を簡潔に出力してください。\n{lgb_probs_str}\n\n【レースデータ】\n{base_prompt}",
    "大穴狙いAI": f"あなたは展開や天候の波乱を重視する大穴狙いAIです。以下のデータから、波乱が起きるシナリオ（1号艇が負ける展開）と穴予想を簡潔に出力してください。\n【レースデータ】\n{base_prompt}",
    "本命党AI": f"あなたは本命重視の堅実なAIです。以下のデータから、最も堅実に決着するシナリオと本命予想を簡潔に出力してください。\n【レースデータ】\n{base_prompt}",
}


def call_model(model, prompt):
    """Ollamaを本番と同じパラメータで呼び出し、応答と速度統計を返す"""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": SYSTEM_RULES,  # 両モデルに同一ルールを注入
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 4000},
    }
    if model in THINK_OFF_MODELS:
        payload["think"] = False  # 思考モードOFF（Ollama対応モデルのみ）
    resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
    resp.raise_for_status()
    r = resp.json()
    eval_count = r.get("eval_count", 0)
    eval_dur = r.get("eval_duration", 1) / 1e9      # 秒
    load_dur = r.get("load_duration", 0) / 1e9
    prompt_dur = r.get("prompt_eval_duration", 0) / 1e9
    total_dur = r.get("total_duration", 0) / 1e9
    text = r.get("response", "")
    thinking = r.get("thinking", "")
    return {
        "text": text,
        "thinking_len": len(thinking) if thinking else 0,
        "tokens": eval_count,
        "tok_per_sec": eval_count / eval_dur if eval_dur > 0 else 0,
        "load_sec": load_dur,
        "prompt_sec": prompt_dur,
        "total_sec": total_dur,
    }


def main():
    results = {}
    for model in MODELS:
        print(f"\n{'='*60}\n### モデル: {model}\n{'='*60}", flush=True)
        results[model] = {}
        for role, prompt in PROMPTS.items():
            print(f"\n--- [{role}] 推論中...", flush=True)
            t0 = time.time()
            try:
                r = call_model(model, prompt)
            except Exception as e:
                print(f"[ERROR] {e}", flush=True)
                results[model][role] = {"error": str(e)}
                continue
            results[model][role] = r
            print(f"完了 ({time.time()-t0:.1f}秒)", flush=True)
            print(f"  生成トークン: {r['tokens']}  速度: {r['tok_per_sec']:.1f} tok/s"
                  f"  (ロード: {r['load_sec']:.1f}s, プロンプト処理: {r['prompt_sec']:.1f}s, 合計: {r['total_sec']:.1f}s)", flush=True)
            if r["thinking_len"]:
                print(f"  ※思考トークンあり (thinking {r['thinking_len']}文字)", flush=True)
            print(f"\n[出力全文]\n{r['text']}\n", flush=True)

    # JSON保存（レポート用）
    with open("reports/qwen_gemma_comparison_with_rules_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print("\n保存完了: reports/qwen_gemma_comparison_raw.json", flush=True)


if __name__ == "__main__":
    main()
