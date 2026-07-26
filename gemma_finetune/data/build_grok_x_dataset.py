"""Grok + X Search を教師にした、時系列安全なGemma学習データ作成。

各過去レースについて、X Searchの対象をレース前7日間に限定する。
レース結果・払戻は教師プロンプトへ渡さないため、未来情報を混ぜない。
"""
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib import error, request

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import build_dataset as bd

API_KEY = os.environ.get("XAI_API_KEY")
MODEL = os.environ.get("GROK_TEACHER_MODEL", "grok-4.5")
API_URL = "https://api.x.ai/v1/responses"
OUT = HERE / "train_grok_x_ranked.jsonl"
AUDIT = HERE / "grok_x_teacher_audit.jsonl"

# koto側のダッシュボードに「どのアプリがGrokをいくら使ったか」を報告するURL
KOTO_USAGE_URL = os.environ.get(
    "KOTO_USAGE_URL", "https://web-production-25bb0.up.railway.app/api/grok-usage/log"
)


def report_grok_usage(usage, cost_usd):
    """トークン数と実費(USD)をkotoのダッシュボードに報告する（失敗しても本処理は止めない）。"""
    try:
        usage = usage or {}
        pt = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        ct = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        body = json.dumps({
            "app": "play-gemma-dataset", "model": MODEL,
            "prompt_tokens": pt, "completion_tokens": ct, "cost_usd": cost_usd,
        }).encode("utf-8")
        req = request.Request(KOTO_USAGE_URL, data=body,
                              headers={"Content-Type": "application/json"}, method="POST")
        request.urlopen(req, timeout=5)
    except Exception:
        pass


def response_text(data):
    parts = []
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "\n".join(parts).strip()


def parse_candidate(text):
    picks, seen = [], set()
    for pick in re.findall(r"[1-6]-[1-6]-[1-6]", text):
        if len(set(pick.split("-"))) == 3 and pick not in seen:
            seen.add(pick)
            picks.append(pick)
        if len(picks) == 5:
            break
    reasoning = text.strip()
    if not reasoning or not picks:
        return None
    return "[推論]\n" + reasoning + "\n\n[買い目]\n" + "\n".join(picks)


def parse_candidates(text):
    """Grokの3案を分解する。形式が崩れた場合は全体を1案として扱う。"""
    chunks = re.split(r"\[案\s*[1-3]\s*\]", text)
    candidates = [parse_candidate(chunk) for chunk in chunks if chunk.strip()]
    candidates = [item for item in candidates if item]
    return candidates[:3] or ([parse_candidate(text)] if parse_candidate(text) else [])


def score_candidate(output, result, payout):
    picks = re.findall(r"[1-6]-[1-6]-[1-6]", output.split("[買い目]")[-1])
    hit = result in picks
    invest = len(picks) * 100
    returned = payout if hit else 0
    roi = returned / invest * 100 if invest else 0
    return {"picks": picks, "hit": hit, "invest": invest, "return": returned, "roi": roi}


def call_grok(prompt, start_date, end_date):
    payload = {
        "model": MODEL,
        "include": ["no_inline_citations"],
        "reasoning_effort": "low",
        "input": [{"role": "user", "content": prompt}],
        "tools": [{"type": "x_search", "from_date": start_date, "to_date": end_date}],
    }
    req = request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as res:
            return json.loads(res.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"network error: {exc}") from exc


def teacher_prompt(situation, race_date):
    return f"""あなたはボートレース予想の教師です。対象レース日は {race_date} です。
添付した事前情報と、X Searchで取得できる『レース前の期間だけ』の投稿を弱い補助材料として使ってください。
結果・払戻・レース後の情報を推測したり参照したりしてはいけません。Xの噂は事実扱いせず、根拠の強さを区別してください。

{situation}

日本語で、性格の異なる予想を3案出してください。各案は必ず次の形式を守ります。
[案1]
[推論]
3〜5文で、コース・選手/モーター・展示/気象・オッズと、X情報を使えた場合だけその扱いを説明する。
[買い目]
3〜5点を 1-2-3 形式で1行ずつ列挙する。
同じ形式で[案2]、[案3]まで続ける。"""


def main():
    n_target = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    if not API_KEY:
        print("[ERROR] XAI_API_KEY is not set.")
        return 1
    res, race, before = bd.load_inputs()
    res = res[res["Result"].astype(str).str.strip() != ""].copy()
    res = res.sort_values("Date", ascending=False)
    written, seen = 0, set()
    total_cost_ticks = 0
    with OUT.open("w", encoding="utf-8") as out, AUDIT.open("w", encoding="utf-8") as audit:
        for _, row in res.iterrows():
            if written >= n_target:
                break
            rid = str(row["ID"])
            if rid in seen:
                continue
            seen.add(rid)
            try:
                race_date = datetime.strptime(str(row["Date"])[:10], "%Y-%m-%d").date()
            except ValueError:
                continue
            odds = bd.odds_for_date(rid.split("_")[0])
            situation = bd.build_situation(rid, race, before, odds)
            if not situation:
                continue
            start_date = (race_date - timedelta(days=7)).isoformat()
            end_date = (race_date - timedelta(days=1)).isoformat()
            try:
                data = call_grok(teacher_prompt(situation, race_date.isoformat()), start_date, end_date)
                text = response_text(data)
                candidates = parse_candidates(text)
            except RuntimeError as exc:
                print(f"[WARN] {rid}: {exc}")
                continue
            if not candidates:
                print(f"[WARN] {rid}: invalid teacher format")
                continue
            result = str(row["Result"]).replace("-", "")
            result = "-".join(result) if len(result) == 3 else result
            try:
                payout = int(float(row.get("Payout", 0)))
            except (TypeError, ValueError):
                payout = 0
            scored = [score_candidate(item, result, payout) for item in candidates]
            # 実結果はここでだけ利用し、Gemmaに渡すinstruction/outputには書き込まない。
            best_index = max(range(len(scored)), key=lambda i: (scored[i]["hit"], scored[i]["roi"], -i))
            output = candidates[best_index]
            out.write(json.dumps({"instruction": situation, "output": output}, ensure_ascii=False) + "\n")
            # 実績が良い案は一度だけ複製し、SFTでの比重を高める（結果そのものは含めない）。
            if scored[best_index]["hit"]:
                out.write(json.dumps({"instruction": situation, "output": output}, ensure_ascii=False) + "\n")
            usage = data.get("usage", {})
            ticks = int(usage.get("cost_in_usd_ticks", 0) or 0)
            total_cost_ticks += ticks
            report_grok_usage(usage, ticks / 10_000_000_000)
            audit.write(json.dumps({"id": rid, "race_date": race_date.isoformat(), "x_from": start_date, "x_to": end_date, "result": result, "payout": payout, "selected_candidate": best_index + 1, "scores": scored, "cost_ticks": ticks}, ensure_ascii=False) + "\n")
            written += 1
            print(f"[{written}/{n_target}] {rid} x={start_date}..{end_date}")
            time.sleep(1)
    print(f"completed: {written} rows -> {OUT}")
    print(f"cost: ${total_cost_ticks / 10_000_000_000:.4f}")
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
