"""Claude Code CLIでボートレースの5点予測を一括生成する。

Claude Maxのログイン済み認証を利用し、APIキーは使わない。ツール・MCP・
ブラウザ連携を無効化して、埋め込んだ入力だけから構造化JSONを生成する。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

from codex_learning import (
    LEARNING_STRATEGY_VERSION,
    build_model_learning_context,
    learning_context_for_prompt,
    save_learning_context,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
INPUT_JSON = DATA_DIR / "daily_race_info.json"
OUTPUT_CSV = DATA_DIR / "daily_claude_predictions.csv"
LEARNING_JSON = DATA_DIR / "claude_learning_summary.json"
SCHEMA_JSON = ROOT / "codex_prediction_schema.json"
CSV_FIELDS = [
    "RaceID",
    "Date",
    "Venue",
    "R",
    "Prediction_Claude",
    "Log_Claude",
    "Stakes_Claude",
    "Strategy_Claude",
    "LearningHistoryCount",
    "LearningClaudeSettledCount",
]
COMBO_PATTERN = re.compile(r"^[1-6]-[1-6]-[1-6]$")


def configure_console() -> None:
    """Windowsコンソールでも日本語を壊さず表示する。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_claude_cli() -> str:
    """Claude Codeの標準的なWindows配置とPATHを確認する。"""
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


def load_input() -> tuple[str, list[dict[str, Any]]]:
    if not INPUT_JSON.is_file():
        raise FileNotFoundError(
            f"入力データがありません: {INPUT_JSON}\n先に generate_battle_data.py を実行してください。"
        )
    with INPUT_JSON.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    races = payload.get("races")
    if not isinstance(races, list) or not races:
        raise ValueError("daily_race_info.jsonに予測対象レースがありません。")
    return str(payload.get("date", "")), races


def load_existing_rows() -> dict[str, dict[str, str]]:
    if not OUTPUT_CSV.is_file():
        return {}
    with OUTPUT_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("RaceID", "")).strip(): row
            for row in csv.DictReader(handle)
            if str(row.get("RaceID", "")).strip()
        }


def compact_race(race: dict[str, Any]) -> dict[str, Any]:
    return {
        "race_id": str(race.get("race_id", "")),
        "date": race.get("date", ""),
        "venue": race.get("venue", ""),
        "race_number": race.get("r", ""),
        "weather": race.get("weather", ""),
        "wind_speed": race.get("wind_speed", ""),
        "wind_direction": race.get("wind_dir", ""),
        "wave": race.get("wave", ""),
        "water_temperature": race.get("water_temp", ""),
        "boats": race.get("boats", []),
        "popular_odds": race.get("odds_top", []),
    }


def build_prompt(races: list[dict[str, Any]], learning_context: dict[str, Any]) -> str:
    race_json = json.dumps(
        [compact_race(race) for race in races],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    learning_json = json.dumps(learning_context, ensure_ascii=False, separators=(",", ":"))
    return f"""You are Claude, one competitor in a Japanese boat-race prediction benchmark.
This is a simulation and evaluation task; do not encourage real-money gambling.

Use only the embedded data. Do not inspect files, run commands, call tools, or access
the network. For every supplied race, predict exactly five distinct trifecta finish
orders. Each pick must contain three different lane numbers from 1 through 6. Rank the
five picks from most likely to least likely. Consider lane advantage, racer class and
win rate, motor and exhibition data, weather, wind, waves, and supplied market odds.

HISTORICAL_LEARNING_JSON contains only results dated before the prediction date. Its
model_feedback contains Claude's own settled predictions only. Use similar-race evidence,
sample size, recent mistakes, all-time results, and recent results without overfitting.
Current race data has priority. Aim to improve five-pick hit rate and simulated ROI over
many races. Do not imitate another model because no other model prediction is supplied.

Return every race exactly once using the required JSON schema. race_id must match the
input exactly. explanation must be concise Japanese, roughly 80-220 characters.

RACE_DATA_JSON:
{race_json}

HISTORICAL_LEARNING_JSON:
{learning_json}
"""


def _load_schema() -> dict[str, Any]:
    with SCHEMA_JSON.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _coerce_predictions(value: Any) -> dict[str, Any] | None:
    """Claudeが配列・順位付き買い目で返した場合も保存前形式へ正規化する。"""
    raw_predictions = value.get("predictions") if isinstance(value, dict) else value
    if not isinstance(raw_predictions, list):
        return None
    normalized = []
    for raw_item in raw_predictions:
        if not isinstance(raw_item, dict):
            return None
        item = dict(raw_item)
        raw_picks = item.get("picks", item.get("ranked_picks", item.get("selections")))
        picks: list[str] = []

        def collect_combos(raw_value: Any) -> None:
            if isinstance(raw_value, dict):
                if "combo" in raw_value:
                    collect_combos(raw_value["combo"])
                    return
                for nested in raw_value.values():
                    collect_combos(nested)
                return
            if isinstance(raw_value, list):
                if len(raw_value) == 3 and all(str(part) in "123456" for part in raw_value):
                    picks.append("-".join(str(part) for part in raw_value))
                    return
                for nested in raw_value:
                    collect_combos(nested)
                return
            text_value = str(raw_value or "").strip()
            if COMBO_PATTERN.fullmatch(text_value):
                picks.append(text_value)

        collect_combos(raw_picks)
        item["picks"] = list(dict.fromkeys(picks))
        if not item.get("explanation"):
            item["explanation"] = item.get("reasoning", item.get("reason", ""))
        normalized.append(item)
    return {"predictions": normalized}


def _extract_structured_output(stdout: str) -> dict[str, Any]:
    """Claude CodeのJSONラッパーと、直接スキーマ出力の両方を受け付ける。"""
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
    command = [
        cli,
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(_load_schema(), ensure_ascii=False, separators=(",", ":")),
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
        os.environ.get("CLAUDE_PREDICTION_MODEL", "sonnet").strip() or "sonnet",
    ]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=ROOT,
        timeout=1800,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "詳細なし").strip()
        raise RuntimeError(
            f"Claude予測に失敗しました (exit={completed.returncode}):\n{detail[-4000:]}"
        )
    return _extract_structured_output(completed.stdout)


def validate_prediction(
    item: dict[str, Any], expected_ids: set[str]
) -> tuple[str, list[str], str]:
    race_id = str(item.get("race_id", "")).strip()
    if race_id not in expected_ids:
        raise ValueError(f"不明なRaceIDが返されました: {race_id}")
    raw_picks = item.get("picks")
    if not isinstance(raw_picks, list) or len(raw_picks) != 5:
        raise ValueError(f"{race_id}: 予測は5点必要です。")
    picks: list[str] = []
    for raw_pick in raw_picks:
        pick = str(raw_pick).strip()
        if not COMBO_PATTERN.fullmatch(pick) or len(set(pick.split("-"))) != 3:
            raise ValueError(f"{race_id}: 不正な組み合わせです: {pick}")
        picks.append(pick)
    if len(set(picks)) != 5:
        raise ValueError(f"{race_id}: 5点の中に重複があります。")
    return race_id, picks, str(item.get("explanation", "")).strip()


def write_rows(existing: dict[str, dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda value: value.get("RaceID", "")):
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def save_rows(
    existing: dict[str, dict[str, str]],
    races_by_id: dict[str, dict[str, Any]],
    result: dict[str, Any],
    learning_context: dict[str, Any],
) -> int:
    expected_ids = set(races_by_id)
    received_ids: set[str] = set()
    staged: dict[str, dict[str, str]] = {}
    predictions = result.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("Claude出力にpredictions配列がありません。")
    for item in predictions:
        if not isinstance(item, dict):
            raise ValueError("Claude出力の予測形式が不正です。")
        race_id, picks, explanation = validate_prediction(item, expected_ids)
        if race_id in received_ids:
            raise ValueError(f"RaceIDが重複しています: {race_id}")
        received_ids.add(race_id)
        race = races_by_id[race_id]
        staged[race_id] = {
            "RaceID": race_id,
            "Date": str(race.get("date", "")),
            "Venue": str(race.get("venue", "")),
            "R": str(race.get("r", "")),
            "Prediction_Claude": ", ".join(picks),
            "Log_Claude": explanation[:2500],
            "Stakes_Claude": ", ".join(f"{pick}:100" for pick in picks),
            "Strategy_Claude": LEARNING_STRATEGY_VERSION,
            "LearningHistoryCount": str(learning_context.get("historical_results_used", 0)),
            "LearningClaudeSettledCount": str(
                learning_context.get("model_feedback", {}).get("settled_count", 0)
            ),
        }
    missing = expected_ids - received_ids
    if missing:
        raise ValueError(f"Claude出力に不足レースがあります: {', '.join(sorted(missing))}")
    # 全件検証が通ってから既存履歴へ反映し、不完全出力を保存しない。
    existing.update(staged)
    write_rows(existing)
    return len(staged)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claudeで当日レースの5点予測を生成します。")
    parser.add_argument("--force", action="store_true", help="当日分の既存予測も作り直す")
    parser.add_argument("--limit", type=int, default=0, help="テスト用の最大レース数")
    parser.add_argument("--dry-run", action="store_true", help="Claudeを呼ばず入力とRAGだけ確認")
    return parser.parse_args()


def main() -> int:
    configure_console()
    args = parse_args()
    target_date, races = load_input()
    if target_date < date.today().isoformat():
        raise ValueError(
            f"過去日への後付け予測は禁止です（対象日: {target_date} / 今日: {date.today().isoformat()}）。"
        )
    existing = load_existing_rows()
    try:
        learning_context = build_model_learning_context(DATA_DIR, target_date, races, "claude")
        save_learning_context(LEARNING_JSON, learning_context)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as error:
        print(f"[WARN] 学習情報を生成できないため当日データのみで予測します: {error}")
        learning_context = {
            "target_date": target_date,
            "strategy_version": LEARNING_STRATEGY_VERSION,
            "model_key": "claude",
            "historical_results_used": 0,
            "model_feedback": {"settled_count": 0, "status": "unavailable"},
            "races": {},
        }

    feedback_count = learning_context.get("model_feedback", {}).get("settled_count", 0)
    print(
        f"学習情報: 過去{learning_context.get('historical_results_used', 0):,}レース / "
        f"Claude結果確定{feedback_count}レース"
    )
    pending = []
    for race in races:
        race_id = str(race.get("race_id", "")).strip()
        prior = existing.get(race_id, {})
        if race_id and (args.force or not str(prior.get("Stakes_Claude", "")).strip()):
            pending.append(race)
    if args.limit > 0:
        pending = pending[: args.limit]
    if not pending:
        print(f"Claude予測は更新済みです（対象日: {target_date}）。")
        return 0

    pending_ids = {str(race.get("race_id", "")) for race in pending}
    prompt_learning = learning_context_for_prompt(learning_context, pending_ids)
    if args.dry_run:
        print(f"DRY-RUN: Claude予測対象 {len(pending)}レース / 呼び出しなし")
        return 0

    print(f"Claudeで{len(pending)}レースを一括予測します（対象日: {target_date}）。")
    result = run_claude(build_prompt(pending, prompt_learning))
    races_by_id = {str(race.get("race_id", "")): race for race in pending}
    saved = save_rows(existing, races_by_id, result, learning_context)
    print(f"完了: {OUTPUT_CSV}に{saved}レースを保存しました。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
