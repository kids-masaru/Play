"""心得集あり版の予測を作る（実験用の新しい予測ストリーム）。

- 既存の予測と同じ入力（daily_race_info.json・同じ学習情報）に、その日の心得集だけを足して予測する。
  違いを心得集だけにして「なし／あり」を同じレースで比べるため。
- 対象：Codex・Claude・学習Gemma（Gemini先生）・学習Qwen（Claude先生）・学習Qwen（Grok+X先生）。
- 出力は既存とは別のCSV（daily_<model>_playbook_predictions.csv）。既存の予測・買い目・
  LINE・実購入には一切使わない。
- 心得集が空のモデルは予測しない（入力が既存と同じになり比較の意味がないため）。
- 朝バッチの最後（既存の予測・公開・CLVの後）に動かし、既存の予測と公開を遅らせない。
  どのモデルが失敗しても終了コードは0（朝バッチを止めない）。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

import playbook as pb

# 既存の予測スクリプトの部品を使い回す。predict_gemma_ft は読み込み時に sys.stdout を
# 差し替えるため、何かを表示する前（ここ）で読み込む。途中で読み込むと、それまでの表示が
# 書き出されずに失われる（10/17の試運転で Claude の結果行が消えた）。
import generate_claude_predictions as claude_base
import generate_codex_predictions as codex_base
import predict_gemma_ft as local_base
from codex_learning import (
    LEARNING_STRATEGY_VERSION,
    build_model_learning_context,
    format_local_learning_context,
    learning_context_for_prompt,
)


# Windowsのタスク実行時も日本語ログが文字化けしないようUTF-8へ固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
INPUT_JSON = DATA_DIR / "daily_race_info.json"
STRATEGY_VERSION = "playbook_v1"
COMBO_PATTERN = re.compile(r"^[1-6]-[1-6]-[1-6]$")

# モデルごとの出力先と列名の接尾辞（PB = playbook）
STREAMS: dict[str, dict[str, str]] = {
    "codex": {"file": "daily_codex_playbook_predictions.csv", "tag": "CodexPB", "kind": "codex"},
    "claude": {"file": "daily_claude_playbook_predictions.csv", "tag": "ClaudePB", "kind": "claude"},
    "gemma_ft": {
        "file": "daily_gemma_ft_playbook_predictions.csv",
        "tag": "GemmaFTPB",
        "kind": "local",
        "ollama_model": "gemma-boat:1b",
    },
    "qwen_claude": {
        "file": "daily_qwen_claude_playbook_predictions.csv",
        "tag": "QwenClaudePB",
        "kind": "local",
        "ollama_model": "qwen-boat-claude:1.7b",
    },
    "qwen_grok_x": {
        "file": "daily_qwen_grok_x_playbook_predictions.csv",
        "tag": "QwenGrokXPB",
        "kind": "local",
        "ollama_model": "qwen-boat-grok-x-v2:1.7b",
    },
}

# Codex・Claude 用の出力形式：既存の5点予測に「実際に使った心得のID」を足す。
# 既存のスキーマファイル（Codexと共用）は変えずに、ここで別に持つ。
PLAYBOOK_PREDICTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["predictions"],
    "properties": {
        "predictions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["race_id", "picks", "explanation", "used_playbook_ids"],
                "properties": {
                    "race_id": {"type": "string"},
                    "picks": {
                        "type": "array",
                        "minItems": 5,
                        "maxItems": 5,
                        "items": {"type": "string", "pattern": "^[1-6]-[1-6]-[1-6]$"},
                    },
                    "explanation": {"type": "string"},
                    "used_playbook_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

PLAYBOOK_INSTRUCTION = """
PLAYBOOK_TEXT is a list of lessons written by a separate reviewer model after studying
YOUR OWN past settled predictions (only results dated before the prediction date).
Apply a lesson only when its conditions match the race; current race data has priority.
For each race, put the ids (like "codex-001") of the lessons you actually applied in
used_playbook_ids. Use an empty list when no lesson was applied. Do not invent ids.
"""


def csv_fields(tag: str) -> list[str]:
    return [
        "RaceID",
        "Date",
        "Venue",
        "R",
        f"Prediction_{tag}",
        f"Log_{tag}",
        f"Stakes_{tag}",
        f"Strategy_{tag}",
        "PlaybookDate",
        "PlaybookHash",
        "PlaybookItems",
        "PlaybookUsedIds",
    ]


# ---------------------------------------------------------------------------
# 入出力
# ---------------------------------------------------------------------------


def load_input(path: Path = INPUT_JSON) -> tuple[str, list[dict[str, Any]]]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    races = payload.get("races")
    if not isinstance(races, list) or not races:
        raise ValueError("daily_race_info.json に予測対象レースがありません。")
    return str(payload.get("date", "")), races


def load_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("RaceID", "")).strip(): row
            for row in csv.DictReader(handle)
            if str(row.get("RaceID", "")).strip()
        }


def write_rows(path: Path, tag: str, rows: dict[str, dict[str, str]]) -> None:
    fields = csv_fields(tag)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in sorted(rows.values(), key=lambda value: value.get("RaceID", "")):
            writer.writerow({field: row.get(field, "") for field in fields})
    os.replace(tmp, path)


def make_row(
    race: dict[str, Any],
    tag: str,
    picks: list[str],
    explanation: str,
    log_text: str,
    injection: dict[str, Any],
    snapshot_date: str,
    used_ids: list[str],
) -> dict[str, str]:
    allowed = set(injection["item_ids"])
    used = [i for i in dict.fromkeys(used_ids) if i in allowed]  # 渡していないIDは捨てる
    return {
        "RaceID": str(race.get("race_id", "")),
        "Date": str(race.get("date", "")),
        "Venue": str(race.get("venue", "")),
        "R": str(race.get("r", "")),
        f"Prediction_{tag}": ", ".join(picks),
        f"Log_{tag}": (explanation or log_text)[:2500],
        f"Stakes_{tag}": ", ".join(f"{pick}:100" for pick in picks),
        f"Strategy_{tag}": STRATEGY_VERSION,
        "PlaybookDate": snapshot_date,
        "PlaybookHash": injection["hash"],
        "PlaybookItems": str(injection["item_count"]),
        "PlaybookUsedIds": " ".join(used),
    }


def extract_used_ids(text: str, injection: dict[str, Any]) -> list[str]:
    """ローカルモデルの出力文から、渡した心得IDが書かれていれば拾う。"""
    return [item_id for item_id in injection["item_ids"] if item_id in str(text or "")]


# ---------------------------------------------------------------------------
# Codex・Claude
# ---------------------------------------------------------------------------


def build_strong_prompt(
    model_key: str,
    races: list[dict[str, Any]],
    learning_context: dict[str, Any],
    injection: dict[str, Any],
) -> str:
    """既存の指示文をそのまま使い、末尾に心得集を足す（違いを心得集だけにする）。"""
    base = codex_base if model_key == "codex" else claude_base
    prompt = base.build_prompt(races, learning_context)
    prompt = prompt.replace(
        "Return every race exactly once using the required JSON schema.",
        "Return every race exactly once using the required JSON schema, including used_playbook_ids.",
    )
    return f"{prompt}\n{PLAYBOOK_INSTRUCTION}\nPLAYBOOK_TEXT:\n{injection['text']}\n"


def call_claude(prompt: str) -> dict[str, Any]:
    base = claude_base
    command = [
        base.find_claude_cli(),
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(PLAYBOOK_PREDICTION_SCHEMA, ensure_ascii=False, separators=(",", ":")),
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
        raise RuntimeError(f"Claude（心得集あり）の予測に失敗 (exit={completed.returncode}): {detail[-1500:]}")
    result = base._extract_structured_output(completed.stdout)
    # 既存の正規化は used_playbook_ids を残すので、そのまま返す
    return result


def call_codex(prompt: str) -> dict[str, Any]:
    base = codex_base
    with tempfile.TemporaryDirectory(prefix="codex-playbook-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        result_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(PLAYBOOK_PREDICTION_SCHEMA, ensure_ascii=False), encoding="utf-8")
        command = [
            base.find_codex_cli(),
            "--sandbox",
            "read-only",
            "--ask-for-approval",
            "never",
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--output-schema",
            str(schema_path),
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
            raise RuntimeError(f"Codex（心得集あり）の予測に失敗 (exit={completed.returncode}): {detail[-1500:]}")
        if not result_path.is_file():
            raise RuntimeError("Codexの構造化出力ファイルが作成されませんでした")
        return json.loads(result_path.read_text(encoding="utf-8"))


STRONG_CALLERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "codex": call_codex,
    "claude": call_claude,
}


def strong_rows(
    model_key: str,
    races: list[dict[str, Any]],
    result: dict[str, Any],
    injection: dict[str, Any],
    snapshot_date: str,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Codex・Claudeの出力を検証し、保存する行と除外理由を返す（不正なレースだけ除外）。"""
    tag = STREAMS[model_key]["tag"]
    races_by_id = {str(race.get("race_id", "")): race for race in races}
    rows: dict[str, dict[str, str]] = {}
    rejected: list[str] = []
    predictions = result.get("predictions") if isinstance(result, dict) else None
    if not isinstance(predictions, list):
        raise RuntimeError("出力に predictions 配列がありません")
    for item in predictions:
        if not isinstance(item, dict):
            rejected.append("予測形式が不正な要素")
            continue
        try:
            race_id, picks, explanation = claude_base.validate_prediction(item, set(races_by_id))
        except ValueError as error:
            rejected.append(str(error))
            continue
        if race_id in rows:
            rejected.append(f"RaceIDが重複しています: {race_id}")
            continue
        used = item.get("used_playbook_ids")
        used_ids = [str(i) for i in used] if isinstance(used, list) else []
        rows[race_id] = make_row(
            races_by_id[race_id], tag, picks, explanation, "", injection, snapshot_date, used_ids
        )
    return rows, rejected


# ---------------------------------------------------------------------------
# ローカルモデル（Ollama）
# ---------------------------------------------------------------------------


def local_prompt(race: dict[str, Any], learning_context: dict[str, Any] | None, injection: dict[str, Any]) -> str:
    """既存のローカル用入力の末尾に心得集を足す。"""
    return f"{local_base.format_race(race, learning_context)}\n{injection['text']}"


def predict_local(
    model_key: str,
    races: list[dict[str, Any]],
    learning_context: dict[str, Any] | None,
    injection: dict[str, Any],
    snapshot_date: str,
    generate: Callable[[str, str], str] | None = None,
) -> dict[str, dict[str, str]]:
    base = local_base
    stream = STREAMS[model_key]
    ollama_model = os.environ.get(f"PLAYBOOK_{model_key.upper()}_MODEL", stream["ollama_model"])
    if generate is None:
        if not base.check_ollama(ollama_model):
            raise RuntimeError(f"Ollama のモデル {ollama_model} を使えません")
        generate = lambda prompt, model: base.call_gemma(prompt, model)  # noqa: E731
    rows: dict[str, dict[str, str]] = {}
    for race in races:
        text = generate(local_prompt(race, learning_context, injection), ollama_model)
        parsed = base.parse_response(text)
        picks = parsed["picks"][:5]
        if not picks:
            print(f"  [WARN] {race.get('venue')} {race.get('r')}R: 買い目なし（保存しない）")
            continue
        rows[str(race["race_id"])] = make_row(
            race,
            stream["tag"],
            picks,
            parsed["reasoning"],
            str(text or "").strip(),
            injection,
            snapshot_date,
            extract_used_ids(text, injection),
        )
        time.sleep(base.SLEEP_BETWEEN_CALLS)
    return rows


# ---------------------------------------------------------------------------
# 1モデル分の実行
# ---------------------------------------------------------------------------


def predict_model(
    model_key: str,
    target_date: str,
    races: list[dict[str, Any]],
    *,
    data_dir: Path = DATA_DIR,
    base_dir: Path = pb.PLAYBOOK_DIR,
    strong_call: Callable[[str, str], dict[str, Any]] | None = None,
    local_generate: Callable[[str, str], str] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """1モデルの心得集あり版を予測して保存する。例外は外へ出さず結果を dict で返す。"""
    stream = STREAMS[model_key]
    out_path = Path(data_dir) / stream["file"]
    result: dict[str, Any] = {"model_key": model_key, "target_date": target_date}
    try:
        snapshot = pb.load_snapshot(model_key, target_date, base_dir)
        if snapshot is None or snapshot["active_count"] == 0:
            return {**result, "status": "empty_playbook"}
        injection = pb.build_injection(snapshot["playbook"])
        result.update({"playbook_date": snapshot["snapshot_date"], "items": injection["item_count"]})

        existing = load_rows(out_path)
        stakes_field = f"Stakes_{stream['tag']}"
        pending = [
            race
            for race in races
            if str(race.get("race_id", "")).strip()
            and (force or not str(existing.get(str(race["race_id"]), {}).get(stakes_field, "")).strip())
        ]
        if not pending:
            return {**result, "status": "up_to_date"}

        # 既存版と同じ学習情報を使う（違いを心得集だけにする）
        try:
            learning_context = build_model_learning_context(Path(data_dir), target_date, races, model_key)
        except (OSError, ValueError, csv.Error, json.JSONDecodeError) as error:
            print(f"  [WARN] {model_key}: 学習情報なしで予測します: {error}")
            learning_context = None

        if dry_run:
            return {**result, "status": "dry_run", "pending": len(pending)}

        if stream["kind"] == "local":
            rows = predict_local(model_key, pending, learning_context, injection, snapshot["snapshot_date"], local_generate)
            rejected: list[str] = []
        else:
            pending_ids = {str(race.get("race_id", "")) for race in pending}
            prompt_learning = (
                learning_context_for_prompt(learning_context, pending_ids)
                if learning_context
                else {"target_date": target_date, "strategy_version": LEARNING_STRATEGY_VERSION, "races": {}}
            )
            prompt = build_strong_prompt(model_key, pending, prompt_learning, injection)
            call = strong_call or (lambda key, text: STRONG_CALLERS[key](text))
            output = call(model_key, prompt)
            rows, rejected = strong_rows(model_key, pending, output, injection, snapshot["snapshot_date"])

        for reason in rejected:
            print(f"  [WARN] {model_key}: 除外: {reason}")
        if not rows:
            return {**result, "status": "failed", "error": "保存できる予測が1件もありません", "pending": len(pending)}
        existing.update(rows)
        write_rows(out_path, stream["tag"], existing)
        used = sum(1 for row in rows.values() if row["PlaybookUsedIds"])
        return {
            **result,
            "status": "done",
            "pending": len(pending),
            "saved": len(rows),
            "used_races": used,
        }
    except (pb.PlaybookError, RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return {**result, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def format_result(outcome: dict[str, Any]) -> str:
    head = outcome["model_key"]
    status = outcome["status"]
    if status == "done":
        return (
            f"{head}: {outcome['saved']}/{outcome['pending']}レース保存"
            f"（心得 {outcome['items']}件・{outcome['playbook_date']}版、心得を使ったレース {outcome['used_races']}）"
        )
    if status == "empty_playbook":
        return f"{head}: 心得集が空のため予測しない"
    if status == "up_to_date":
        return f"{head}: 今日の分は保存済み"
    if status == "dry_run":
        return f"{head}: DRY-RUN 対象 {outcome['pending']}レース（心得 {outcome['items']}件・{outcome['playbook_date']}版）"
    return f"[WARN] {head}: 失敗: {outcome.get('error')}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="心得集あり版の予測を作ります（実験用）。")
    parser.add_argument(
        "--models",
        default=",".join(pb.MODEL_KEYS),
        help=f"対象モデル（カンマ区切り。既定: {','.join(pb.MODEL_KEYS)}）",
    )
    parser.add_argument("--force", action="store_true", help="今日の保存済み分も作り直す")
    parser.add_argument("--dry-run", action="store_true", help="モデルを呼ばず、対象と心得集の版だけ確認")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in models if m not in STREAMS]
    if unknown:
        print(f"[ERROR] 心得集の対象外のモデルです: {', '.join(unknown)}", file=sys.stderr)
        return 2
    try:
        target_date, races = load_input()
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"[WARN] 入力を読めないため心得集あり版の予測をしません: {error}")
        return 0
    today = date.today().isoformat()
    if target_date != today:
        # 当日以外（前日の入力が残っている等）への予測は、後付けや未来情報の混入になりうるので行わない
        print(f"[WARN] 入力の対象日 {target_date} が今日 {today} ではないため予測しません")
        return 0
    print(f"心得集あり版の予測 開始（対象日: {target_date} / {len(races)}レース）")
    for model_key in models:
        print(format_result(predict_model(model_key, target_date, races, force=args.force, dry_run=args.dry_run)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
