"""モデルごとの心得集（プレイブック）を保存・検証・注入する土台部品。

心得集は項目単位で育てる（ACE型）。振り返り役から受け取るのは差分
（add / update / disable）だけで、全面書き直しは受け付けない。
このモジュールは既存の予測・採点・公開処理から呼ばれない単体の部品で、
LLMの呼び出しは行わない（振り返り本体は playbook_reflect.py が担当する）。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
PLAYBOOK_DIR = ROOT / "daily_data" / "playbooks"
CHANGES_FILE_NAME = "changes.jsonl"
HISTORY_DIR_NAME = "history"

SCHEMA_VERSION = "playbook_v1"

# 心得集を載せるモデル（キーは jev_shadow.MODEL_SOURCES の id と同じ）
MODEL_KEYS = ("codex", "claude", "gemma_ft", "qwen_claude", "qwen_grok_x")

# 振り返り役の割り当て（たすき掛け）。自分自身は振り返らせない。
REFLECTOR_ASSIGNMENT = {
    "codex": "claude",
    "gemma_ft": "claude",
    "qwen_claude": "claude",
    "qwen_grok_x": "claude",
    "claude": "codex",
}

MAX_ACTIVE_ITEMS = 30  # 有効項目の上限（モデルごと）
MAX_TEXT_CHARS = 200  # 1項目の本文の上限
MAX_REASON_CHARS = 200  # 無効化理由の上限
MAX_OPS_PER_DAY = 5  # 1日あたりの差分操作の上限
MAX_EVIDENCE_IDS = 10  # 1項目に残す根拠レースIDの上限

# 予測へ注入する文字数の上限（強いモデルは多め、ローカルモデルは控えめ）
INJECT_CHAR_LIMITS = {"codex": 4000, "claude": 4000}
DEFAULT_INJECT_CHAR_LIMIT = 1500

INJECTION_HEADER = "## 予測の心得（過去の振り返りから）"

VALID_OPS = ("add", "update", "disable")
STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PlaybookError(ValueError):
    """心得集の形式・差分が不正なときの例外。"""


class FutureLeakError(PlaybookError):
    """対象日当日以降の結果が混ざったときの例外（時系列ガード）。"""


# ---------------------------------------------------------------------------
# 共通の小道具
# ---------------------------------------------------------------------------


def _parse_date(value: Any, label: str = "日付") -> date:
    """YYYY-MM-DD 形式の文字列を date に変換する。形式違いは PlaybookError。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not DATE_PATTERN.match(text):
        raise PlaybookError(f"{label}が YYYY-MM-DD 形式ではありません: {value!r}")
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise PlaybookError(f"{label}が存在しない日付です: {value!r}") from exc


def _check_model_key(model_key: str) -> str:
    if model_key not in MODEL_KEYS:
        raise PlaybookError(f"心得集の対象外のモデルです: {model_key!r}")
    return model_key


def _normalize_text(value: Any, label: str, max_chars: int) -> str:
    """本文を1行にそろえ、空・長すぎを拒否する。"""
    if not isinstance(value, str):
        raise PlaybookError(f"{label}が文字列ではありません")
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        raise PlaybookError(f"{label}が空です")
    if len(text) > max_chars:
        raise PlaybookError(f"{label}が{max_chars}文字を超えています（{len(text)}文字）")
    return text


def _normalize_evidence(value: Any) -> list[str]:
    """根拠レースIDの一覧を文字列リストにそろえる（重複除去・上限つき）。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise PlaybookError("根拠レースIDはリストで指定してください")
    result: list[str] = []
    for race_id in value:
        text = str(race_id or "").strip()
        if text and text not in result:
            result.append(text)
    return result[:MAX_EVIDENCE_IDS]


def _atomic_write_json(path: Path, data: Any) -> None:
    """書き込み途中で落ちても壊れたファイルを残さないよう、一時ファイル経由で置き換える。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# 心得集の作成・読み書き
# ---------------------------------------------------------------------------


def empty_playbook(model_key: str) -> dict[str, Any]:
    """項目が1件もない心得集を作る。"""
    return {
        "schema": SCHEMA_VERSION,
        "model_key": _check_model_key(model_key),
        "updated_for": None,  # 最後に差分を反映した対象日
        "next_seq": 1,  # 次に採番する項目番号
        "items": [],
    }


def playbook_path(model_key: str, base_dir: Path = PLAYBOOK_DIR) -> Path:
    return Path(base_dir) / f"{_check_model_key(model_key)}.json"


def validate_playbook(playbook: Any, model_key: str | None = None) -> dict[str, Any]:
    """読み込んだ心得集の構造を確認する。壊れていれば PlaybookError。"""
    if not isinstance(playbook, dict):
        raise PlaybookError("心得集がオブジェクトではありません")
    if playbook.get("schema") != SCHEMA_VERSION:
        raise PlaybookError(f"心得集の版が違います: {playbook.get('schema')!r}")
    key = _check_model_key(str(playbook.get("model_key") or ""))
    if model_key is not None and key != model_key:
        raise PlaybookError(f"心得集のモデルが違います: {key!r}（期待: {model_key!r}）")
    items = playbook.get("items")
    if not isinstance(items, list):
        raise PlaybookError("心得集の items がリストではありません")
    seen: set[str] = set()
    active = 0
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            raise PlaybookError("id のない項目があります")
        if item["id"] in seen:
            raise PlaybookError(f"項目IDが重複しています: {item['id']}")
        seen.add(item["id"])
        if item.get("status") not in (STATUS_ACTIVE, STATUS_DISABLED):
            raise PlaybookError(f"項目の状態が不正です: {item['id']}")
        if item["status"] == STATUS_ACTIVE:
            active += 1
            _normalize_text(item.get("text"), f"項目 {item['id']} の本文", MAX_TEXT_CHARS)
    if active > MAX_ACTIVE_ITEMS:
        raise PlaybookError(f"有効項目が上限{MAX_ACTIVE_ITEMS}件を超えています（{active}件）")
    if not isinstance(playbook.get("next_seq"), int) or playbook["next_seq"] < 1:
        raise PlaybookError("next_seq が不正です")
    return playbook


def load_playbook(model_key: str, base_dir: Path = PLAYBOOK_DIR) -> dict[str, Any]:
    """心得集を読む。まだ無ければ空の心得集を返す。壊れていれば PlaybookError。"""
    path = playbook_path(model_key, base_dir)
    if not path.exists():
        return empty_playbook(model_key)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlaybookError(f"心得集を読めません: {path}: {exc}") from exc
    return validate_playbook(data, model_key)


def save_playbook(playbook: dict[str, Any], base_dir: Path = PLAYBOOK_DIR) -> Path:
    """検証してから心得集を保存する。"""
    validate_playbook(playbook)
    path = playbook_path(playbook["model_key"], base_dir)
    _atomic_write_json(path, playbook)
    return path


def active_items(playbook: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in playbook.get("items", []) if item.get("status") == STATUS_ACTIVE]


def content_hash(playbook: dict[str, Any]) -> str:
    """有効項目の id と本文だけから作るハッシュ（成績の更新では変わらない）。"""
    content = sorted((item["id"], item["text"]) for item in active_items(playbook))
    raw = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 時系列ガード
# ---------------------------------------------------------------------------


def guard_chronology(target_date: Any, result_dates: Iterable[Any]) -> str | None:
    """振り返りに使う結果がすべて対象日より前かを確かめ、最終日を返す。

    1件でも対象日当日以降の結果があれば FutureLeakError を出して処理を拒否する。
    結果が1件もなければ None を返す。
    """
    target = _parse_date(target_date, "対象日")
    last: date | None = None
    for value in result_dates:
        day = _parse_date(value, "結果の日付")
        if day >= target:
            raise FutureLeakError(
                f"対象日 {target.isoformat()} 以降の結果（{day.isoformat()}）が含まれています"
            )
        if last is None or day > last:
            last = day
    return last.isoformat() if last else None


# ---------------------------------------------------------------------------
# 差分の検証と反映
# ---------------------------------------------------------------------------


def _find_active(items_by_id: dict[str, dict[str, Any]], item_id: Any) -> dict[str, Any]:
    item = items_by_id.get(str(item_id or ""))
    if item is None:
        raise PlaybookError(f"存在しない項目IDです: {item_id!r}")
    if item.get("status") != STATUS_ACTIVE:
        raise PlaybookError(f"無効化済みの項目です: {item_id!r}")
    return item


def apply_ops(
    playbook: dict[str, Any],
    ops: Any,
    *,
    target_date: Any,
    result_last_date: Any,
    reflector: str,
) -> dict[str, Any]:
    """振り返り役の差分を検証して反映した新しい心得集を返す（元の心得集は変えない）。

    - 結果の最終日が対象日以降なら FutureLeakError（全体を拒否）。
    - 操作が5件を超える・リストでない場合は PlaybookError（全面書き直し扱いで全体を拒否）。
    - それ以外は1件ずつ検証し、不正な操作だけを rejected に入れて残りは反映する。

    戻り値: {"playbook": 新しい心得集, "applied": [...], "rejected": [...]}
    applied / rejected の各要素はそのまま changes.jsonl に書ける形。
    """
    validate_playbook(playbook)
    target = _parse_date(target_date, "対象日").isoformat()
    last = None
    if result_last_date is not None:
        last = guard_chronology(target, [result_last_date])
    if not isinstance(ops, list):
        raise PlaybookError("差分はリストで渡してください")
    if len(ops) > MAX_OPS_PER_DAY:
        raise PlaybookError(
            f"差分が{len(ops)}件あります。1日{MAX_OPS_PER_DAY}件までで、全面書き直しは受け付けません"
        )

    new_playbook = copy.deepcopy(playbook)
    items_by_id = {item["id"]: item for item in new_playbook["items"]}
    model_key = new_playbook["model_key"]
    touched: set[str] = set()
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    def base_entry(op: Any) -> dict[str, Any]:
        return {
            "date": target,
            "model_key": model_key,
            "reflector": reflector,
            "result_last_date": last,
            "op": op.get("op") if isinstance(op, dict) else None,
        }

    for op in ops:
        entry = base_entry(op)
        try:
            if not isinstance(op, dict):
                raise PlaybookError("操作がオブジェクトではありません")
            kind = op.get("op")
            if kind not in VALID_OPS:
                raise PlaybookError(f"知らない操作です: {kind!r}")

            if kind == "add":
                text = _normalize_text(op.get("text"), "追加する本文", MAX_TEXT_CHARS)
                if len(active_items(new_playbook)) >= MAX_ACTIVE_ITEMS:
                    raise PlaybookError(f"有効項目が上限{MAX_ACTIVE_ITEMS}件に達しています")
                if any(item["text"] == text for item in active_items(new_playbook)):
                    raise PlaybookError("同じ本文の有効項目がすでにあります")
                item_id = f"{model_key}-{new_playbook['next_seq']:03d}"
                new_playbook["next_seq"] += 1
                item = {
                    "id": item_id,
                    "text": text,
                    "status": STATUS_ACTIVE,
                    "created_at": target,
                    "updated_at": target,
                    "evidence_race_ids": _normalize_evidence(op.get("evidence_race_ids")),
                    "use_count": 0,
                    "use_hits": 0,
                    "use_profit": 0,
                    "disabled_reason": None,
                }
                new_playbook["items"].append(item)
                items_by_id[item_id] = item
                touched.add(item_id)
                entry.update({"item_id": item_id, "text": text, "status": "applied"})

            else:
                item_id = str(op.get("id") or "")
                if item_id in touched:
                    raise PlaybookError(f"同じ日に同じ項目を2回変更しようとしています: {item_id}")
                item = _find_active(items_by_id, item_id)
                if kind == "update":
                    text = _normalize_text(op.get("text"), "修正後の本文", MAX_TEXT_CHARS)
                    if text == item["text"]:
                        raise PlaybookError("本文が変わっていません")
                    entry["previous_text"] = item["text"]
                    item["text"] = text
                    evidence = _normalize_evidence(op.get("evidence_race_ids"))
                    if evidence:
                        merged = evidence + [r for r in item.get("evidence_race_ids", []) if r not in evidence]
                        item["evidence_race_ids"] = merged[:MAX_EVIDENCE_IDS]
                    entry["text"] = text
                else:  # disable
                    reason = _normalize_text(op.get("reason"), "無効化の理由", MAX_REASON_CHARS)
                    item["status"] = STATUS_DISABLED
                    item["disabled_reason"] = reason
                    entry["reason"] = reason
                item["updated_at"] = target
                touched.add(item_id)
                entry.update({"item_id": item_id, "status": "applied"})

            applied.append(entry)
        except PlaybookError as exc:
            entry.update({"status": "rejected", "reject_reason": str(exc)})
            if isinstance(op, dict):
                entry["raw"] = {k: op.get(k) for k in ("op", "id", "text", "reason")}
            rejected.append(entry)

    if applied:
        new_playbook["updated_for"] = target
    validate_playbook(new_playbook)
    return {"playbook": new_playbook, "applied": applied, "rejected": rejected}


def append_changes(entries: Iterable[dict[str, Any]], base_dir: Path = PLAYBOOK_DIR) -> int:
    """反映・拒否した差分を changes.jsonl に追記し、書いた件数を返す。"""
    rows = list(entries)
    if not rows:
        return 0
    path = Path(base_dir) / CHANGES_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps({**row, "recorded_at": recorded_at}, ensure_ascii=False) + "\n")
    return len(rows)


def record_usage(
    playbook: dict[str, Any], item_ids: Iterable[Any], *, hit: bool, profit: float
) -> dict[str, Any]:
    """予測で参考にした心得の使用回数・的中数・収支を足した新しい心得集を返す。

    存在しないIDは無視する（モデルの出力が形式に合わないこともあるため）。
    """
    new_playbook = copy.deepcopy(playbook)
    items_by_id = {item["id"]: item for item in new_playbook["items"]}
    for item_id in dict.fromkeys(str(i) for i in item_ids):
        item = items_by_id.get(item_id)
        if item is None:
            continue
        item["use_count"] = int(item.get("use_count", 0)) + 1
        item["use_hits"] = int(item.get("use_hits", 0)) + (1 if hit else 0)
        item["use_profit"] = item.get("use_profit", 0) + profit
    return new_playbook


# ---------------------------------------------------------------------------
# 日付版（確定版）の保存と読み出し
# ---------------------------------------------------------------------------


def snapshot_path(model_key: str, target_date: Any, base_dir: Path = PLAYBOOK_DIR) -> Path:
    day = _parse_date(target_date, "対象日").isoformat()
    return Path(base_dir) / HISTORY_DIR_NAME / _check_model_key(model_key) / f"{day}.json"


def save_snapshot(
    playbook: dict[str, Any], target_date: Any, base_dir: Path = PLAYBOOK_DIR
) -> dict[str, Any]:
    """その日の予測に使う確定版を保存し、版情報（日付・ハッシュ・項目数）を返す。"""
    validate_playbook(playbook)
    day = _parse_date(target_date, "対象日").isoformat()
    info = {
        "model_key": playbook["model_key"],
        "snapshot_date": day,
        "hash": content_hash(playbook),
        "active_count": len(active_items(playbook)),
    }
    _atomic_write_json(
        snapshot_path(playbook["model_key"], day, base_dir), {**info, "playbook": playbook}
    )
    return info


def load_snapshot(
    model_key: str, target_date: Any, base_dir: Path = PLAYBOOK_DIR
) -> dict[str, Any] | None:
    """対象日に使う確定版を返す。その日の版が無ければ、それより前で最新の版を返す。

    振り返りが失敗した日も前日版で予測を続けるための仕組み。
    対象日より後の版は決して返さない。1つも無ければ None。
    """
    target = _parse_date(target_date, "対象日")
    folder = Path(base_dir) / HISTORY_DIR_NAME / _check_model_key(model_key)
    if not folder.exists():
        return None
    candidates: list[tuple[date, Path]] = []
    for path in folder.glob("*.json"):
        try:
            day = _parse_date(path.stem)
        except PlaybookError:
            continue
        if day <= target:
            candidates.append((day, path))
    for day, path in sorted(candidates, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            playbook = validate_playbook(data.get("playbook"), model_key)
        except (OSError, json.JSONDecodeError, PlaybookError, AttributeError):
            continue  # 壊れた版は飛ばして、さらに前の版を探す
        return {
            "model_key": model_key,
            "snapshot_date": day.isoformat(),
            "hash": content_hash(playbook),
            "active_count": len(active_items(playbook)),
            "playbook": playbook,
        }
    return None


# ---------------------------------------------------------------------------
# 予測への注入
# ---------------------------------------------------------------------------


def inject_char_limit(model_key: str) -> int:
    return INJECT_CHAR_LIMITS.get(model_key, DEFAULT_INJECT_CHAR_LIMIT)


def _injection_order(item: dict[str, Any]) -> tuple:
    # 収支の良い順 → 新しい順 → ID順（同点でも結果が毎回同じになるように）
    return (-float(item.get("use_profit", 0) or 0), _sort_key_desc(item.get("updated_at")), item["id"])


def _sort_key_desc(value: Any) -> int:
    try:
        return -_parse_date(value).toordinal()
    except PlaybookError:
        return 0


def build_injection(playbook: dict[str, Any], char_limit: int | None = None) -> dict[str, Any]:
    """予測プロンプトに足す心得の文章と、その記録用情報を作る。

    戻り値: {"text", "item_ids", "item_count", "hash"}。
    有効項目が無いときは text が空文字になる（心得集なしと同じ入力になる）。
    """
    validate_playbook(playbook)
    limit = char_limit if char_limit is not None else inject_char_limit(playbook["model_key"])
    lines: list[str] = []
    item_ids: list[str] = []
    used = len(INJECTION_HEADER)
    for item in sorted(active_items(playbook), key=_injection_order):
        line = f"- [{item['id']}] {item['text']}"
        if used + 1 + len(line) > limit:
            continue  # 長い項目は飛ばし、短い項目が入るなら入れる
        lines.append(line)
        item_ids.append(item["id"])
        used += 1 + len(line)
    text = "\n".join([INJECTION_HEADER, *lines]) if lines else ""
    return {
        "text": text,
        "item_ids": item_ids,
        "item_count": len(item_ids),
        "hash": content_hash(playbook),
    }
