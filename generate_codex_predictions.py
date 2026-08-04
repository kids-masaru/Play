"""Codex CLI でボートレースの5点予測を一括生成する。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from codex_learning import (
    LEARNING_STRATEGY_VERSION,
    build_codex_learning_context,
    learning_context_for_prompt,
    save_learning_context,
)


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
INPUT_JSON = DATA_DIR / "daily_race_info.json"
OUTPUT_CSV = DATA_DIR / "daily_codex_predictions.csv"
LEARNING_JSON = DATA_DIR / "codex_learning_summary.json"
SCHEMA_JSON = ROOT / "codex_prediction_schema.json"
CSV_FIELDS = [
    "RaceID",
    "Date",
    "Venue",
    "R",
    "Prediction_Codex",
    "Log_Codex",
    "Stakes_Codex",
    "Strategy_Codex",
    "LearningHistoryCount",
    "LearningCodexSettledCount",
]
COMBO_PATTERN = re.compile(r"^[1-6]-[1-6]-[1-6]$")


def configure_console() -> None:
    """Windows コンソールでも日本語を壊さず表示する。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_codex_cli() -> str:
    """Codex Desktop 同梱CLIを優先し、PATHもフォールバックとして使う。"""
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "OpenAI"
        / "Codex"
        / "bin"
        / "codex.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    path_cli = shutil.which("codex") or shutil.which("codex.exe")
    if path_cli:
        return path_cli
    raise FileNotFoundError(
        "Codex CLI が見つかりません。Codex Desktopを起動し、ChatGPTでログインしてください。"
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
        raise ValueError("daily_race_info.json に予測対象レースがありません。")
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
    """Codexへ渡す情報を、予測に必要な項目だけに絞る。"""
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
    return f"""You are one competitor in a Japanese boat-race prediction benchmark.
This is a simulation and evaluation task; do not encourage real-money gambling.

Use only the race data embedded below. Do not inspect files, run commands, use tools,
or access the network. For every supplied race, predict exactly five distinct trifecta
finish orders. Each pick must contain three different lane numbers from 1 through 6.
Rank the five picks from most likely to least likely. Consider lane advantage, racer
class and win rate, motor/exhibition information when present, weather, wind, waves,
and the supplied market odds. Do not copy another AI's prediction because none is supplied.

HISTORICAL_LEARNING_JSON contains only races completed before the prediction date.
Use its similar-race rates, actual outcomes, and Codex feedback as supporting evidence.
Do not mechanically copy a frequent combination. Give current race data priority, respect
sample sizes, and do not overfit preliminary Codex feedback. Aim to improve both five-pick
hit rate and simulated ROI over many races, not a single day's result.

Return every race exactly once using the required JSON schema. In explanation, write a
concise Japanese rationale (roughly 80-220 Japanese characters). The race_id must match
the input exactly.

RACE_DATA_JSON:
{race_json}

HISTORICAL_LEARNING_JSON:
{learning_json}
"""


def run_codex(prompt: str) -> dict[str, Any]:
    cli = find_codex_cli()
    with tempfile.TemporaryDirectory(prefix="codex-boat-") as temp_dir:
        result_path = Path(temp_dir) / "result.json"
        command = [
            cli,
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--output-schema",
            str(SCHEMA_JSON),
            "--output-last-message",
            str(result_path),
        ]
        model = os.environ.get("CODEX_PREDICTION_MODEL", "").strip()
        if model:
            command.extend(["--model", model])
        command.append("-")

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
            raise RuntimeError(f"Codex予測に失敗しました (exit={completed.returncode}):\n{detail[-4000:]}")
        if not result_path.is_file():
            raise RuntimeError("Codexの構造化出力ファイルが作成されませんでした。")
        with result_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)


def validate_prediction(item: dict[str, Any], expected_ids: set[str]) -> tuple[str, list[str], str]:
    race_id = str(item.get("race_id", "")).strip()
    if race_id not in expected_ids:
        raise ValueError(f"不明なRaceIDが返されました: {race_id}")

    raw_picks = item.get("picks")
    if not isinstance(raw_picks, list) or len(raw_picks) != 5:
        raise ValueError(f"{race_id}: 予測は5点必要です。")

    picks: list[str] = []
    for raw_pick in raw_picks:
        pick = str(raw_pick).strip()
        if not COMBO_PATTERN.fullmatch(pick):
            raise ValueError(f"{race_id}: 不正な組み合わせです: {pick}")
        lanes = pick.split("-")
        if len(set(lanes)) != 3:
            raise ValueError(f"{race_id}: 同じ艇番が重複しています: {pick}")
        picks.append(pick)
    if len(set(picks)) != 5:
        raise ValueError(f"{race_id}: 5点の中に重複があります。")

    explanation = str(item.get("explanation", "")).strip()
    return race_id, picks, explanation


def save_rows(
    existing: dict[str, dict[str, str]],
    races_by_id: dict[str, dict[str, Any]],
    result: dict[str, Any],
    learning_context: dict[str, Any],
) -> int:
    expected_ids = set(races_by_id)
    received_ids: set[str] = set()
    saved_count = 0
    predictions = result.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("Codex出力に predictions 配列がありません。")

    for item in predictions:
        if not isinstance(item, dict):
            raise ValueError("Codex出力の予測形式が不正です。")
        race_id, picks, explanation = validate_prediction(item, expected_ids)
        if race_id in received_ids:
            raise ValueError(f"RaceIDが重複しています: {race_id}")
        received_ids.add(race_id)
        race = races_by_id[race_id]
        existing[race_id] = {
            "RaceID": race_id,
            "Date": str(race.get("date", "")),
            "Venue": str(race.get("venue", "")),
            "R": str(race.get("r", "")),
            "Prediction_Codex": ", ".join(picks),
            "Log_Codex": explanation[:2500],
            "Stakes_Codex": ", ".join(f"{pick}:100" for pick in picks),
            "Strategy_Codex": LEARNING_STRATEGY_VERSION,
            "LearningHistoryCount": str(learning_context.get("historical_results_used", 0)),
            "LearningCodexSettledCount": str(learning_context.get("codex_feedback", {}).get("settled_count", 0)),
        }
        saved_count += 1

    missing = expected_ids - received_ids
    if missing:
        raise ValueError(f"Codex出力に不足レースがあります: {', '.join(sorted(missing))}")

    write_rows(existing)
    return saved_count


def write_rows(existing: dict[str, dict[str, str]]) -> None:
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(existing.values(), key=lambda value: value.get("RaceID", "")):
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codexで当日レースの5点予測を生成します。")
    parser.add_argument("--force", action="store_true", help="既存予測も作り直す")
    parser.add_argument("--limit", type=int, default=0, help="テスト用の最大レース数")
    return parser.parse_args()


def main() -> int:
    configure_console()
    args = parse_args()
    target_date, races = load_input()
    existing = load_existing_rows()

    try:
        learning_context = build_codex_learning_context(DATA_DIR, target_date, races)
        save_learning_context(LEARNING_JSON, learning_context)
        feedback_count = learning_context.get("codex_feedback", {}).get("settled_count", 0)
        print(
            f"学習情報: 過去{learning_context.get('historical_results_used', 0):,}レース / "
            f"Codex結果確定{feedback_count}レース"
        )
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as error:
        # 学習情報の一時的な不備で、当日の予測全体を止めない。
        print(f"[WARN] 学習情報を生成できないため当日データのみで予測します: {error}")
        learning_context = {
            "target_date": target_date,
            "strategy_version": LEARNING_STRATEGY_VERSION,
            "historical_results_used": 0,
            "codex_feedback": {"settled_count": 0, "status": "unavailable"},
            "races": {},
        }

    pending = []
    for race in races:
        race_id = str(race.get("race_id", "")).strip()
        prior = existing.get(race_id, {})
        if race_id and (args.force or not str(prior.get("Stakes_Codex", "")).strip()):
            pending.append(race)
    if args.limit > 0:
        pending = pending[: args.limit]

    if not pending:
        print(f"Codex予測は更新済みです（対象日: {target_date}）。")
        return 0

    print(f"Codexで{len(pending)}レースを一括予測します（対象日: {target_date}）。")
    pending_ids = {str(race.get("race_id", "")) for race in pending}
    prompt_learning = learning_context_for_prompt(learning_context, pending_ids)
    result = run_codex(build_prompt(pending, prompt_learning))
    races_by_id = {str(race.get("race_id", "")): race for race in pending}
    saved = save_rows(existing, races_by_id, result, learning_context)
    print(f"完了: {OUTPUT_CSV} に {saved} レースを保存しました。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        raise SystemExit(1)
