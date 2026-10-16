"""強いモデルが各モデルの結果を振り返り、心得集の差分を作って反映する（たすき掛け）。

- Claude が Codex・学習Gemma・学習Qwen2種を、Codex が Claude を振り返る（自己採点しない）。
- 材料は対象モデル自身の確定済み予測と、レース結果・事前情報だけ。他モデルの買い目は見せない。
- 呼び出しは1モデル1日1回。前回の振り返り以降の新しいレースだけを、新しい順に最大40件使う
  （旧反省会のように古い順に処理して遅れが積み上がるのを避ける）。
- どのモデルの振り返りが失敗しても、ほかのモデル・既存の予測は止めない。失敗した日は
  心得集を変えず、予測側は playbook.load_snapshot で前日以前の版を使う。
- 実購入・既存の買い目・LINE通知には一切関わらない。
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
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import playbook as pb
from codex_learning import (
    MODEL_PREDICTION_CONFIGS,
    load_history_records,
    parse_stakes,
)


# Windowsのタスク実行時も日本語ログが文字化けしないようUTF-8へ固定する。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
STATE_FILE_NAME = "reflect_state.json"
REFLECTIONS_DIR_NAME = "reflections"

MAX_RACES_PER_REFLECTION = 40  # 1回の振り返りに渡す最大レース数（新しい順）
MAX_EXPLANATION_CHARS = 200  # 材料に入れる各予測の理由文の上限
CALL_TIMEOUT_SEC = 900

LOCAL_MODELS = {"gemma_ft", "qwen_claude", "qwen_grok_x"}

# 振り返り役の出力形式。Codex の構造化出力にも通るよう、全項目を required にして
# 使わない項目は null を返させる。
REFLECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "ops"],
    "properties": {
        "summary": {"type": "string"},
        "ops": {
            "type": "array",
            "maxItems": pb.MAX_OPS_PER_DAY,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["op", "id", "text", "reason", "evidence_race_ids"],
                "properties": {
                    "op": {"type": "string", "enum": list(pb.VALID_OPS)},
                    "id": {"type": ["string", "null"]},
                    "text": {"type": ["string", "null"]},
                    "reason": {"type": ["string", "null"]},
                    "evidence_race_ids": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


class ReflectorError(RuntimeError):
    """振り返り役の呼び出し・出力の解析に失敗したときの例外。"""


# ---------------------------------------------------------------------------
# 材料（対象モデル自身の確定済み予測）
# ---------------------------------------------------------------------------


def _read_prediction_rows(data_dir: Path, model_key: str) -> list[dict[str, str]]:
    config = MODEL_PREDICTION_CONFIGS[model_key]
    path = Path(data_dir) / config["file"]
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def collect_settled(
    data_dir: Path,
    target_date: str,
    model_key: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """対象日より前に結果が確定した、対象モデル自身の予測を古い順に返す。"""
    config = MODEL_PREDICTION_CONFIGS[model_key]
    log_field = config["stakes"].replace("Stakes_", "Log_")
    start = str(config.get("feedback_start_date", ""))
    record_by_id = {row["race_id"]: row for row in records}
    settled: list[dict[str, Any]] = []
    for row in _read_prediction_rows(data_dir, model_key):
        prediction_date = str(row.get("Date", ""))
        if not prediction_date or prediction_date >= target_date:
            continue  # 当日以降の予測は材料にしない
        if start and prediction_date < start:
            continue
        record = record_by_id.get(str(row.get("RaceID", "")).strip())
        picks = parse_stakes(row.get(config["stakes"]))
        if not record or not picks or record["date"] >= target_date:
            continue
        actual = record["result"]
        investment = sum(stake for _, stake in picks)
        hit_stake = sum(stake for combo, stake in picks if combo == actual)
        returned = hit_stake * record["payout"] / 100
        explanation = re.sub(r"\s+", " ", str(row.get(log_field, "") or "")).strip()
        settled.append({
            "race_id": record["race_id"],
            "date": record["date"],
            "venue": record["venue"],
            "r": record["r"],
            "conditions": {
                "lane1_strength": record.get("lane1_strength"),
                "top_win_rate_lane": record.get("top_lane"),
                "win_rates": record.get("win_rates"),
                "ranks": record.get("ranks"),
                "wind": record.get("wind_bucket"),
                "wave": record.get("wave_bucket"),
            },
            "picks": [combo for combo, _ in picks],
            "explanation": explanation[:MAX_EXPLANATION_CHARS],
            "actual": actual,
            "payout": round(record["payout"]),
            "hit": hit_stake > 0,
            "stake_yen": round(investment),
            "profit": round(returned - investment),
        })
    settled.sort(key=lambda item: (item["date"], item["race_id"]))
    return settled


def select_material(
    settled: list[dict[str, Any]],
    last_result_date: str | None,
    limit: int = MAX_RACES_PER_REFLECTION,
) -> list[dict[str, Any]]:
    """前回の振り返りより後のレースだけを、新しい順に最大 limit 件選ぶ（古い順に並べ直して返す）。"""
    fresh = [row for row in settled if not last_result_date or row["date"] > last_result_date]
    return fresh[-limit:] if limit > 0 else []


def summarize_material(material: list[dict[str, Any]]) -> dict[str, Any]:
    races = len(material)
    hits = sum(1 for row in material if row["hit"])
    investment = sum(row.get("stake_yen", 0) for row in material)
    profit = sum(row["profit"] for row in material)
    return {
        "races": races,
        "hits": hits,
        "hit_rate_pct": round(hits / races * 100, 1) if races else 0,
        "profit_yen": profit,
        "roi_pct": round((investment + profit) / investment * 100, 1) if investment else 0,
    }


# ---------------------------------------------------------------------------
# 指示文
# ---------------------------------------------------------------------------


def _model_label(model_key: str) -> str:
    return MODEL_PREDICTION_CONFIGS[model_key]["label"]


def build_prompt(
    model_key: str,
    target_date: str,
    playbook: dict[str, Any],
    material: list[dict[str, Any]],
) -> str:
    """振り返り役へ渡す指示文を作る。材料は対象モデル自身の確定結果だけ。"""
    items = [
        {
            "id": item["id"],
            "text": item["text"],
            "created_at": item.get("created_at"),
            "use_count": item.get("use_count", 0),
            "use_hits": item.get("use_hits", 0),
            "use_profit_yen": item.get("use_profit", 0),
        }
        for item in pb.active_items(playbook)
    ]
    style = (
        "対象は小さなローカルモデルなので、心得は短く単純に、数字や条件で機械的に判断できる形にする。"
        if model_key in LOCAL_MODELS
        else "対象は大きなモデルなので、条件と根拠を含めた具体的な心得にしてよい。"
    )
    playbook_json = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    material_json = json.dumps(material, ensure_ascii=False, separators=(",", ":"))
    summary_json = json.dumps(summarize_material(material), ensure_ascii=False)
    return f"""あなたはボートレース予測AIの「振り返り役」です。これは予測精度を比べるシミュレーション・評価作業で、実際の賭けを勧めるものではありません。
ファイルの参照・コマンド実行・ツール・ネットワークは使わず、下に埋め込んだデータだけで判断してください。

対象モデル: {_model_label(model_key)}（{model_key}）
次に予測する日: {target_date}（材料はすべてこれより前に確定したレースです）
対象モデルは毎レース3連単5点（各100円）を予想しています。

やること：
1. SETTLED_RACES（対象モデル自身の確定済み予想と結果）を見て、外れ・当たりの理由を考える。
2. 対象モデル用の心得集（CURRENT_PLAYBOOK）を良くする差分だけを ops に出す。
   - add: 新しい心得を追加（text と evidence_race_ids を入れる。id は null）
   - update: 既存の心得の本文を直す（id と新しい text を入れる）
   - disable: 役に立っていない・間違っている心得を無効にする（id と reason を入れる）
3. summary に、今回の振り返りの要点を日本語200字程度で書く。

心得のルール：
- 「どんな条件のとき → 予想をどう変えるか」の形で具体的に書く（会場・レース番号帯・風・波・1号艇の強さ・級別・勝率差など）。「風を考慮すべき」のような一般論は書かない。
- 複数のレースで確認できた傾向だけを心得にする。根拠のレースIDを evidence_race_ids に入れる（SETTLED_RACES にあるIDだけ）。
- 1項目200字以内、日本語。操作は最大{pb.MAX_OPS_PER_DAY}件。強い根拠がなければ ops は空でよい。
- 心得集の全面書き直しはしない。似た心得がすでにあれば add ではなく update にする。有効な心得は最大{pb.MAX_ACTIVE_ITEMS}件。
- 使用回数が多いのに収支が悪い心得は、直すか無効にする。
- {style}
- ほかのモデルの予想は材料にありません。真似を勧める心得は書かない。

MATERIAL_SUMMARY:
{summary_json}

CURRENT_PLAYBOOK:
{playbook_json}

SETTLED_RACES:
{material_json}
"""


# ---------------------------------------------------------------------------
# 振り返り役の呼び出し
# ---------------------------------------------------------------------------


def _parse_reflection(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict) and isinstance(value.get("ops"), list):
        return {"summary": str(value.get("summary") or ""), "ops": value["ops"]}
    return None


def extract_claude_output(stdout: str) -> dict[str, Any]:
    """Claude Code の JSON ラッパーから振り返り結果を取り出す。"""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ReflectorError(f"ClaudeのJSON出力を解析できません: {exc}") from exc
    if parsed := _parse_reflection(payload):
        return parsed
    if isinstance(payload, dict):
        for key in ("structured_output", "structuredOutput", "output"):
            if parsed := _parse_reflection(payload.get(key)):
                return parsed
        result = payload.get("result")
        if parsed := _parse_reflection(result):
            return parsed
        if isinstance(result, str):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", result.strip(), flags=re.IGNORECASE)
            first, last = cleaned.find("{"), cleaned.rfind("}")
            if first >= 0 and last > first:
                try:
                    if parsed := _parse_reflection(json.loads(cleaned[first:last + 1])):
                        return parsed
                except json.JSONDecodeError:
                    pass
    raise ReflectorError("Claudeの出力に ops がありません")


def call_claude(prompt: str) -> dict[str, Any]:
    from generate_claude_predictions import find_claude_cli

    command = [
        find_claude_cli(),
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(REFLECTION_SCHEMA, ensure_ascii=False, separators=(",", ":")),
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
        os.environ.get("CLAUDE_REFLECT_MODEL", "sonnet").strip() or "sonnet",
    ]
    completed = subprocess.run(
        command,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=ROOT,
        timeout=CALL_TIMEOUT_SEC,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "詳細なし").strip()
        raise ReflectorError(f"Claudeの振り返りに失敗 (exit={completed.returncode}): {detail[-1500:]}")
    return extract_claude_output(completed.stdout)


def call_codex(prompt: str) -> dict[str, Any]:
    from generate_codex_predictions import find_codex_cli

    with tempfile.TemporaryDirectory(prefix="codex-reflect-") as temp_dir:
        schema_path = Path(temp_dir) / "schema.json"
        result_path = Path(temp_dir) / "result.json"
        schema_path.write_text(json.dumps(REFLECTION_SCHEMA, ensure_ascii=False), encoding="utf-8")
        command = [
            find_codex_cli(),
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
        model = os.environ.get("CODEX_REFLECT_MODEL", "").strip()
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
            timeout=CALL_TIMEOUT_SEC,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "詳細なし").strip()
            raise ReflectorError(f"Codexの振り返りに失敗 (exit={completed.returncode}): {detail[-1500:]}")
        if not result_path.is_file():
            raise ReflectorError("Codexの構造化出力ファイルが作成されませんでした")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ReflectorError(f"Codexの出力を解析できません: {exc}") from exc
    if parsed := _parse_reflection(payload):
        return parsed
    raise ReflectorError("Codexの出力に ops がありません")


REFLECTOR_CALLERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "claude": call_claude,
    "codex": call_codex,
}


def default_call(reflector: str, prompt: str) -> dict[str, Any]:
    caller = REFLECTOR_CALLERS.get(reflector)
    if caller is None:
        raise ReflectorError(f"知らない振り返り役です: {reflector}")
    return caller(prompt)


# ---------------------------------------------------------------------------
# 状態（前回どこまで振り返ったか）
# ---------------------------------------------------------------------------


def load_state(base_dir: Path) -> dict[str, Any]:
    path = Path(base_dir) / STATE_FILE_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[WARN] 振り返りの状態ファイルを読めないため、最初からとして扱います: {path}")
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict[str, Any], base_dir: Path) -> None:
    pb._atomic_write_json(Path(base_dir) / STATE_FILE_NAME, state)


def _sanitize_ops(ops: Any, material_ids: set[str]) -> Any:
    """根拠レースIDを材料にあるものだけに絞る（ほかはモデルの作り話として捨てる）。"""
    if not isinstance(ops, list):
        return ops
    cleaned = []
    for op in ops:
        if isinstance(op, dict):
            op = dict(op)
            evidence = op.get("evidence_race_ids")
            if isinstance(evidence, list):
                op["evidence_race_ids"] = [r for r in evidence if str(r) in material_ids]
        cleaned.append(op)
    return cleaned


# ---------------------------------------------------------------------------
# 1モデル分の振り返り
# ---------------------------------------------------------------------------


def reflect_model(
    model_key: str,
    target_date: str,
    records: list[dict[str, Any]],
    *,
    data_dir: Path = DATA_DIR,
    base_dir: Path = pb.PLAYBOOK_DIR,
    call: Callable[[str, str], dict[str, Any]] = default_call,
    state: dict[str, Any] | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """1モデルの心得集を振り返りで更新する。例外は外へ出さず、結果を dict で返す。

    status: done（反映した）/ no_material（新しい確定結果がない）/ skipped（今日は済み）/
            dry_run / failed（失敗。心得集は変えない）
    """
    reflector = pb.REFLECTOR_ASSIGNMENT[model_key]
    state = state if state is not None else load_state(base_dir)
    previous = state.get(model_key) or {}
    result: dict[str, Any] = {"model_key": model_key, "reflector": reflector, "target_date": target_date}

    if not force and previous.get("target_date") == target_date and previous.get("status") in ("done", "no_material"):
        return {**result, "status": "skipped"}

    try:
        playbook = pb.load_playbook(model_key, base_dir)
        settled = collect_settled(data_dir, target_date, model_key, records)
        last_result_date = previous.get("result_last_date")
        if force and previous.get("target_date") == target_date:
            # 同じ日のやり直しでは、その日の前回の起点から材料を取り直す
            last_result_date = previous.get("previous_result_last_date")
        material = select_material(settled, last_result_date)
        material_last = pb.guard_chronology(target_date, [row["date"] for row in material])
        result["material_races"] = len(material)
        result["result_last_date"] = material_last

        if dry_run:
            prompt = build_prompt(model_key, target_date, playbook, material)
            return {**result, "status": "dry_run", "prompt_chars": len(prompt)}

        if not material:
            snapshot = pb.save_snapshot(playbook, target_date, base_dir)
            state[model_key] = {
                "target_date": target_date,
                "status": "no_material",
                "result_last_date": last_result_date,
                "previous_result_last_date": last_result_date,
                "hash": snapshot["hash"],
            }
            return {**result, "status": "no_material", "snapshot": snapshot}

        prompt = build_prompt(model_key, target_date, playbook, material)
        output = call(reflector, prompt)
        ops = _sanitize_ops(output.get("ops"), {row["race_id"] for row in material})
        applied = pb.apply_ops(
            playbook,
            ops,
            target_date=target_date,
            result_last_date=material_last,
            reflector=reflector,
        )
        new_playbook = applied["playbook"]
        pb.save_playbook(new_playbook, base_dir)
        pb.append_changes(applied["applied"] + applied["rejected"], base_dir)
        snapshot = pb.save_snapshot(new_playbook, target_date, base_dir)

        # 振り返りの生出力は非公開フォルダに残す（週1の見直しで使う）
        pb._atomic_write_json(
            Path(base_dir) / REFLECTIONS_DIR_NAME / model_key / f"{target_date}.json",
            {
                "model_key": model_key,
                "reflector": reflector,
                "target_date": target_date,
                "result_last_date": material_last,
                "material_race_ids": [row["race_id"] for row in material],
                "material_summary": summarize_material(material),
                "summary": output.get("summary", ""),
                "ops": output.get("ops"),
                "applied": len(applied["applied"]),
                "rejected": len(applied["rejected"]),
                "snapshot_hash": snapshot["hash"],
                "created_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        state[model_key] = {
            "target_date": target_date,
            "status": "done",
            "result_last_date": material_last,
            "previous_result_last_date": last_result_date,
            "hash": snapshot["hash"],
        }
        return {
            **result,
            "status": "done",
            "applied": len(applied["applied"]),
            "rejected": len(applied["rejected"]),
            "active_count": snapshot["active_count"],
            "snapshot": snapshot,
        }
    except (pb.PlaybookError, ReflectorError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        # 失敗しても心得集は変えない。予測側は前日以前の版を使う。
        return {**result, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def run(
    target_date: str,
    model_keys: list[str],
    *,
    data_dir: Path = DATA_DIR,
    base_dir: Path = pb.PLAYBOOK_DIR,
    call: Callable[[str, str], dict[str, Any]] = default_call,
    force: bool = False,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """指定モデルを順に振り返る。1モデルの失敗でほかを止めない。"""
    target = pb._parse_date(target_date, "対象日").isoformat()
    records = load_history_records(Path(data_dir), target)
    state = load_state(base_dir)
    results = []
    for model_key in model_keys:
        outcome = reflect_model(
            model_key,
            target,
            records,
            data_dir=data_dir,
            base_dir=base_dir,
            call=call,
            state=state,
            force=force,
            dry_run=dry_run,
        )
        results.append(outcome)
        if not dry_run:
            save_state(state, base_dir)  # 途中で落ちても済んだモデルはやり直さない
    return results


def format_result(outcome: dict[str, Any]) -> str:
    head = f"{outcome['model_key']}（振り返り役: {outcome['reflector']}）"
    status = outcome["status"]
    if status == "done":
        return (
            f"{head}: 反映 {outcome['applied']}件 / 拒否 {outcome['rejected']}件 / "
            f"有効 {outcome['active_count']}件（材料 {outcome['material_races']}レース・〜{outcome['result_last_date']}）"
        )
    if status == "no_material":
        return f"{head}: 新しい確定結果なし（心得集は変更なし）"
    if status == "skipped":
        return f"{head}: 今日は振り返り済み"
    if status == "dry_run":
        return f"{head}: DRY-RUN 材料 {outcome['material_races']}レース / 指示文 {outcome['prompt_chars']:,}文字"
    return f"[WARN] {head}: 失敗（心得集は前日版のまま）: {outcome.get('error')}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="強いモデルの振り返りで心得集を更新します（たすき掛け）。")
    parser.add_argument("--date", default=date.today().isoformat(), help="次に予測する日（既定: 今日）")
    parser.add_argument(
        "--models",
        default=",".join(pb.MODEL_KEYS),
        help=f"対象モデル（カンマ区切り。既定: {','.join(pb.MODEL_KEYS)}）",
    )
    parser.add_argument("--force", action="store_true", help="今日済みでも振り返り直す")
    parser.add_argument("--dry-run", action="store_true", help="振り返り役を呼ばず、材料と指示文の大きさだけ確認")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    unknown = [m for m in models if m not in pb.MODEL_KEYS]
    if unknown:
        print(f"[ERROR] 心得集の対象外のモデルです: {', '.join(unknown)}", file=sys.stderr)
        return 2
    print(f"心得集の振り返り 開始（対象日: {args.date}）")
    for outcome in run(args.date, models, force=args.force, dry_run=args.dry_run):
        print(format_result(outcome))
    # 振り返りの失敗で朝バッチ全体を止めないため、常に 0 を返す
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
