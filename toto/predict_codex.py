"""ChatGPT 認証の Codex CLI で toto の 1X2 予測を一括生成する。"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from predict_gemini import build_context, collect_unique_matches, load_stats_model


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCHEMA_PATH = ROOT / "codex_toto_schema.json"
STRATEGY_VERSION = "feedback_v1"


def configure_console() -> None:
    """Windows コンソールでも日本語を壊さず表示する。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def find_codex_cli() -> str:
    """Codex Desktop 同梱 CLI を優先し、PATH もフォールバックにする。"""
    desktop_cli = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Programs"
        / "OpenAI"
        / "Codex"
        / "bin"
        / "codex.exe"
    )
    if desktop_cli.is_file():
        return str(desktop_cli)
    path_cli = shutil.which("codex") or shutil.which("codex.exe")
    if path_cli:
        return path_cli
    raise FileNotFoundError(
        "Codex CLI が見つかりません。Codex Desktop を起動し、ChatGPT でログインしてください。"
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def match_key(match: dict[str, Any]) -> str:
    """同じ試合を toto / mini toto 間で共通に識別する。"""
    return "|".join(
        str(match.get(field) or "").strip() for field in ("date", "home", "away")
    )


def load_feedback(target_round: int) -> dict[str, Any]:
    """対象回より前に確定した Codex 予測だけを集計する。"""
    evaluated: list[dict[str, str]] = []
    for raw_path in glob.glob(str(DATA_DIR / "codex_round_*.json")):
        try:
            codex_data = load_json(Path(raw_path))
            round_no = int(codex_data.get("round", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if round_no >= target_round:
            continue

        settled_path = DATA_DIR / f"settled_{round_no}.json"
        if not settled_path.is_file():
            continue
        try:
            settled = load_json(settled_path)
        except (OSError, json.JSONDecodeError):
            continue
        actual_by_key = {
            match_key(item): str(item.get("actual", ""))
            for item in settled.get("results", [])
            if item.get("actual") in {"H", "D", "A"}
        }
        for prediction in codex_data.get("predictions", []):
            predicted = str(prediction.get("pick", ""))
            actual = actual_by_key.get(match_key(prediction), "")
            if predicted in {"H", "D", "A"} and actual:
                evaluated.append(
                    {
                        "home": str(prediction.get("home", "")),
                        "away": str(prediction.get("away", "")),
                        "predicted": predicted,
                        "actual": actual,
                    }
                )

    hits = sum(row["predicted"] == row["actual"] for row in evaluated)
    by_pick: dict[str, dict[str, int]] = {}
    for pick in ("H", "D", "A"):
        rows = [row for row in evaluated if row["predicted"] == pick]
        by_pick[pick] = {
            "n": len(rows),
            "hits": sum(row["actual"] == pick for row in rows),
        }
    recent_misses = [
        row for row in evaluated if row["predicted"] != row["actual"]
    ][-24:]
    return {
        "strategy_version": STRATEGY_VERSION,
        "settled_predictions": len(evaluated),
        "hits": hits,
        "hit_rate": round(hits / len(evaluated), 4) if evaluated else None,
        "by_predicted_pick": by_pick,
        "recent_misses": recent_misses,
    }


def compact_match(match: dict[str, Any], stats: Any) -> dict[str, Any]:
    """統計モデルの確率を付け、Codex に渡す情報を絞る。"""
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
    return f"""You are one competitor in a Japanese toto football prediction benchmark.
This is a simulation and evaluation task; do not encourage real-money gambling.

Use only the match data embedded below. Do not inspect files, run commands, use tools,
or access the network. Predict every supplied match exactly once as H (home win),
D (draw), or A (away win). The stats_model probabilities are trained only on matches
before the fixture date. Treat them as useful evidence, not an answer to copy.

HISTORICAL_CODEX_FEEDBACK contains Codex predictions whose results were already settled
before this round. Use sample size, pick-specific accuracy, and recent mistakes to calibrate
your judgment. Do not overfit small samples. Prefer a realistic mix of H/D/A outcomes.

Return the required JSON schema. match_key must exactly match the input. confidence is an
integer from 1 to 99. reasoning must be concise Japanese (roughly 50-140 characters) and
state the main evidence and uncertainty.

MATCH_DATA_JSON:
{match_json}

HISTORICAL_CODEX_FEEDBACK:
{feedback_json}
"""


def run_codex(prompt: str) -> dict[str, Any]:
    cli = find_codex_cli()
    with tempfile.TemporaryDirectory(prefix="codex-toto-") as temp_dir:
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
            str(SCHEMA_PATH),
            "--output-last-message",
            str(result_path),
        ]
        model = os.environ.get("CODEX_TOTO_MODEL", "").strip()
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
            cwd=ROOT.parent,
            timeout=1800,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "詳細なし").strip()
            raise RuntimeError(
                f"Codexのtoto予測に失敗しました (exit={completed.returncode}):\n{detail[-4000:]}"
            )
        if not result_path.is_file():
            raise RuntimeError("Codex の構造化出力が作成されませんでした。")
        return load_json(result_path)


def validate_result(
    result: dict[str, Any], expected: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    predictions = result.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("Codex 出力に predictions 配列がありません。")

    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in predictions:
        key = str(item.get("match_key", ""))
        if key not in expected:
            raise ValueError(f"不明な試合が返されました: {key}")
        if key in seen:
            raise ValueError(f"同じ試合が重複しています: {key}")
        pick = str(item.get("pick", ""))
        if pick not in {"H", "D", "A"}:
            raise ValueError(f"{key}: 予測は H/D/A のいずれかが必要です。")
        confidence = int(item.get("confidence", 0))
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
        raise ValueError(f"Codex 出力に予測が無い試合があります: {sorted(missing)}")
    return output


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Codex で toto の 1X2 予測を一括生成")
    parser.add_argument("round", type=int, help="toto の回号")
    parser.add_argument("--dry-run", action="store_true", help="Codexは呼ばず入力だけ確認")
    args = parser.parse_args()

    round_path = DATA_DIR / f"round_{args.round}.json"
    if not round_path.is_file():
        raise FileNotFoundError(f"対象データがありません: {round_path}")
    round_data = load_json(round_path)
    raw_matches = collect_unique_matches(round_data)
    stats = load_stats_model()
    matches = [compact_match(item, stats) for item in raw_matches]
    expected = {item["match_key"]: item for item in matches}
    feedback = load_feedback(args.round)
    prompt = build_prompt(matches, feedback)

    print(f"=== toto Codex予測 第{args.round}回 ===")
    print(
        f"対象 {len(matches)}試合 / 過去フィードバック "
        f"{feedback['settled_predictions']}試合"
    )
    if args.dry_run:
        print(prompt)
        return 0

    result = run_codex(prompt)
    predictions = validate_result(result, expected)
    output = {
        "round": args.round,
        "model": os.environ.get("CODEX_TOTO_MODEL", "Codex (ChatGPT)") or "Codex (ChatGPT)",
        "strategy_version": STRATEGY_VERSION,
        "generated_date": date.today().isoformat(),
        "feedback_settled_count": feedback["settled_predictions"],
        "predictions": predictions,
    }
    output_path = DATA_DIR / f"codex_round_{args.round}.json"
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, indent=2)
    print(f"完了: {output_path} ({len(predictions)}試合)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
