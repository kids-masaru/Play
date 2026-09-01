"""Claude Max認証のClaude Code CLIでtotoの1X2予測を一括生成する。"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import re
from datetime import date
from pathlib import Path
from typing import Any

from model_feedback import STRATEGY_VERSION, load_model_feedback, match_key
from predict_gemini import build_context, collect_unique_matches, load_stats_model


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCHEMA_PATH = ROOT / "codex_toto_schema.json"


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_claude_cli() -> str:
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "claude.exe",
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "claude",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    path_cli = shutil.which("claude") or shutil.which("claude.exe")
    if path_cli:
        return path_cli
    raise FileNotFoundError(
        "Claude Code CLIが見つかりません。Claude Codeをインストールしてログインしてください。"
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def is_on_sale(round_data: dict[str, Any]) -> bool:
    """締切日が今日以降のくじが1つでもある場合だけ新規予測を許可する。"""
    today = date.today().isoformat()
    deadlines = [
        str(section.get("deadline", ""))[:10]
        for section in (round_data.get("kuji") or {}).values()
        if section and section.get("deadline")
    ]
    return any(deadline >= today for deadline in deadlines)


def compact_match(match: dict[str, Any], stats: Any) -> dict[str, Any]:
    _, stat_out = build_context(match, stats)
    return {
        "match_key": match_key(match),
        "date": match.get("date", ""),
        "kickoff": match.get("kickoff", ""),
        "home": match.get("home", ""),
        "away": match.get("away", ""),
        "stats_model": stat_out,
    }


def build_prompt(matches: list[dict[str, Any]], feedback: dict[str, Any]) -> str:
    match_json = json.dumps(matches, ensure_ascii=False, separators=(",", ":"))
    feedback_json = json.dumps(feedback, ensure_ascii=False, separators=(",", ":"))
    return f"""You are Claude, one competitor in a Japanese toto football prediction benchmark.
This is a simulation and evaluation task; do not encourage real-money gambling.

Use only the embedded match data. Do not inspect files, run commands, call tools, or
access the network. Predict every supplied match exactly once as H (home win), D (draw),
or A (away win). stats_model probabilities are trained only on matches before the fixture
date. Treat them as evidence, not an answer to copy.

HISTORICAL_MODEL_FEEDBACK contains only Claude's predictions from settled rounds before
this target round. Use sample size, pick-specific accuracy, and recent mistakes to calibrate
the decision without overfitting. Prefer a realistic mix of H/D/A outcomes. No other model's
prediction is supplied.

Return the required JSON schema. match_key must exactly match the input. confidence must be
an integer from 1 to 99. reasoning must be concise Japanese, roughly 50-140 characters.

MATCH_DATA_JSON:
{match_json}

HISTORICAL_MODEL_FEEDBACK:
{feedback_json}
"""


def _coerce_predictions(value: Any) -> dict[str, Any] | None:
    """Claudeがpredictionsを直接配列で返した場合も共通形式へ正規化する。"""
    raw_predictions = value.get("predictions") if isinstance(value, dict) else value
    if not isinstance(raw_predictions, list):
        return None
    return {"predictions": raw_predictions}


def _extract_structured_output(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"ClaudeのJSON出力を解析できません: {error}") from error
    if isinstance(payload, dict):
        for key in ("structured_output", "structuredOutput", "output"):
            candidate = payload.get(key)
            if coerced := _coerce_predictions(candidate):
                return coerced
        result_value = payload.get("result")
        if coerced := _coerce_predictions(result_value):
            return coerced
        if isinstance(result_value, str):
            cleaned = result_value.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
            candidates = [cleaned]
            first, last = cleaned.find("{"), cleaned.rfind("}")
            if first >= 0 and last > first:
                candidates.append(cleaned[first:last + 1])
            for candidate in candidates:
                try:
                    nested = json.loads(candidate)
                    if coerced := _coerce_predictions(nested):
                        return coerced
                except json.JSONDecodeError:
                    continue
    if coerced := _coerce_predictions(payload):
        return coerced
    keys = sorted(payload) if isinstance(payload, dict) else []
    preview = str(payload.get("result", ""))[:300] if isinstance(payload, dict) else ""
    raise RuntimeError(
        f"Claudeの構造化出力にpredictionsがありません。keys={keys}, result={preview!r}"
    )


def run_claude(prompt: str) -> dict[str, Any]:
    cli = find_claude_cli()
    schema = load_json(SCHEMA_PATH)
    command = [
        cli,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-chrome",
        "--disable-slash-commands",
        "--model",
        os.environ.get("CLAUDE_TOTO_MODEL", "sonnet").strip() or "sonnet",
    ]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=ROOT.parent,
        timeout=1800,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "詳細なし").strip()
        raise RuntimeError(
            f"Claudeのtoto予測に失敗しました (exit={completed.returncode}):\n{detail[-4000:]}"
        )
    return _extract_structured_output(completed.stdout)


def validate_result(
    result: dict[str, Any], expected: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    predictions = result.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("Claude出力にpredictions配列がありません。")
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in predictions:
        if not isinstance(item, dict):
            raise ValueError("Claude出力の予測形式が不正です。")
        key = str(item.get("match_key", ""))
        if key not in expected:
            raise ValueError(f"不明な試合が返されました: {key}")
        if key in seen:
            raise ValueError(f"同じ試合が重複しています: {key}")
        pick = str(item.get("pick", ""))
        if pick not in {"H", "D", "A"}:
            raise ValueError(f"{key}: 予測はH/D/Aのいずれかが必要です。")
        confidence = int(item.get("confidence", 0))
        if not 1 <= confidence <= 99:
            raise ValueError(f"{key}: confidenceは1〜99が必要です。")
        base = expected[key]
        output.append(
            {
                "date": base.get("date", ""),
                "home": base.get("home", ""),
                "away": base.get("away", ""),
                "kickoff": base.get("kickoff", ""),
                "pick": pick,
                "confidence": f"{confidence}%",
                "reasoning": str(item.get("reasoning", "")).strip()[:1200],
                "stats": base.get("stats_model"),
            }
        )
        seen.add(key)
    missing = set(expected) - seen
    if missing:
        raise ValueError(f"Claude出力に予測が無い試合があります: {sorted(missing)}")
    return output


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Claudeでtotoの1X2予測を一括生成")
    parser.add_argument("round", type=int, help="totoの回号")
    parser.add_argument("--dry-run", action="store_true", help="Claudeを呼ばず入力だけ確認")
    parser.add_argument("--force", action="store_true", help="販売中の既存予測も作り直す")
    args = parser.parse_args()

    round_path = DATA_DIR / f"round_{args.round}.json"
    if not round_path.is_file():
        raise FileNotFoundError(f"対象データがありません: {round_path}")
    round_data = load_json(round_path)
    if not is_on_sale(round_data):
        raise ValueError(f"第{args.round}回は販売終了済みのため、後付け予測しません。")

    output_path = DATA_DIR / f"claude_round_{args.round}.json"
    if output_path.is_file() and not args.force:
        existing = load_json(output_path)
        if existing.get("predictions"):
            print(f"Claude予測は生成済みです: {output_path}")
            return 0

    raw_matches = collect_unique_matches(round_data)
    stats = load_stats_model()
    matches = [compact_match(item, stats) for item in raw_matches]
    expected = {item["match_key"]: item for item in matches}
    feedback = load_model_feedback(DATA_DIR, args.round, "claude")
    prompt = build_prompt(matches, feedback)

    print(f"=== toto Claude予測 第{args.round}回 ===")
    print(f"対象 {len(matches)}試合 / 過去フィードバック {feedback['settled_predictions']}試合")
    if args.dry_run:
        print("DRY-RUN: 入力・時系列ガード・フィードバック生成は正常です。")
        return 0

    result = run_claude(prompt)
    predictions = validate_result(result, expected)
    output = {
        "round": args.round,
        "model": os.environ.get("CLAUDE_TOTO_MODEL", "Claude Code (Sonnet)")
        or "Claude Code (Sonnet)",
        "strategy_version": STRATEGY_VERSION,
        "generated_date": date.today().isoformat(),
        "feedback_settled_count": feedback["settled_predictions"],
        "predictions": predictions,
    }
    # 全試合の検証が通った後だけ一括保存する。
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    print(f"完了: {output_path} ({len(predictions)}試合)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
