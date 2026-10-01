"""Jevで既存モデルの買い目を審査し、シャドー判定だけを保存する。

このスクリプトは実購入、既存買い目、LINE通知を変更しない。Jevの出力は
将来の比較検証用ラベルとして保存し、十分な実績が集まるまで本番判断へ使わない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# Windowsのタスク実行時も日本語ログが文字化けしないようUTF-8へ固定する。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


ROOT = Path(__file__).resolve().parent
PUBLIC_DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
DEFAULT_RACE_INFO = PUBLIC_DATA_DIR / "daily_race_info.json"
DEFAULT_PERFORMANCE = PUBLIC_DATA_DIR / "model_performance.json"
DEFAULT_CLV = PUBLIC_DATA_DIR / "clv_summary.json"
DEFAULT_OUTPUT = PUBLIC_DATA_DIR / "jev_shadow_decisions.json"
DEFAULT_HISTORY = ROOT / "daily_data" / "jev_shadow_history.jsonl"
DEFAULT_EXPERIMENT_PERFORMANCE = PUBLIC_DATA_DIR / "jev_pairing_performance.json"

JST = timezone(timedelta(hours=9))
API_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
STRATEGY_VERSION = "jev_shadow_v2"
QUESTION_VERSION = "jev_boatrace_gate_v1"
SELECTOR_QUESTION_VERSION = "jev_boatrace_selector_v1"
EXPERIMENT_VERSION = "jev_pairing_v1"
MAX_CANDIDATES = 12
MIN_ACTIVE_MODELS = 2


MODEL_SOURCES = (
    {
        "id": "base_gemma",
        "label": "基本Gemma",
        "pick_field": "ai_picks_llm",
        "performance_key": "stakes",
        "clv_key": None,
    },
    {
        "id": "gemini",
        "label": "Gemini",
        "pick_field": "ai_picks_gemini",
        "performance_key": "stakes_gemini",
        "clv_key": "gemini",
    },
    {
        "id": "grok",
        "label": "Grok",
        "pick_field": "ai_picks_grok",
        "performance_key": "stakes_grok",
        "clv_key": "grok",
    },
    {
        "id": "gemma_ft",
        "label": "学習Gemma（Gemini先生）",
        "pick_field": "ai_picks_gemmaft",
        "performance_key": "stakes_gemmaft",
        "clv_key": "gemma",
    },
    {
        "id": "qwen_claude",
        "label": "学習Qwen（Claude先生）",
        "pick_field": "ai_picks_gemmaclaude",
        "performance_key": "stakes_gemmaclaude",
        "clv_key": "gemma_claude",
    },
    {
        "id": "qwen_grok_x",
        "label": "学習Qwen（Grok+X先生）",
        "pick_field": "ai_picks_gemmagrokx",
        "performance_key": "stakes_gemmagrokx",
        "clv_key": "gemma_grok_x",
    },
    {
        "id": "codex",
        "label": "Codex",
        "pick_field": "ai_picks_codex",
        "performance_key": "stakes_codex",
        "clv_key": "codex",
    },
    {
        "id": "claude",
        "label": "Claude",
        "pick_field": "ai_picks_claude",
        "performance_key": "stakes_claude",
        "clv_key": "claude",
    },
)

PAIRING_ARMS = (
    {
        "id": "codex_raw",
        "type": "raw_model",
        "source_ids": ("codex",),
        "minimum_models": 1,
    },
    {
        "id": "codex_jev",
        "type": "jev_selector",
        "source_ids": ("codex",),
        "minimum_models": 1,
    },
    {
        "id": "claude_raw",
        "type": "raw_model",
        "source_ids": ("claude",),
        "minimum_models": 1,
    },
    {
        "id": "claude_jev",
        "type": "jev_selector",
        "source_ids": ("claude",),
        "minimum_models": 1,
    },
    {
        "id": "all_models_jev",
        "type": "jev_gate_and_selector",
        "source_ids": None,
        "minimum_models": MIN_ACTIVE_MODELS,
    },
)

COMBO_PATTERN = re.compile(
    r"(?<!\d)([1-6])\s*[-ー–―]\s*([1-6])\s*[-ー–―]\s*([1-6])"
    r"(?:\s*[:：]\s*(\d+(?:\.\d+)?))?"
)


def log(message: str) -> None:
    """日本語を含む進捗を時刻付きで表示する。"""

    now = datetime.now(JST).strftime("%H:%M:%S")
    print(f"[{now}] {message}", flush=True)


def load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    """JSONを読み込み、任意入力の欠落は空辞書として扱う。"""

    if not path.exists():
        if required:
            raise FileNotFoundError(f"入力ファイルがありません: {path}")
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"JSONの最上位がobjectではありません: {path}")
    return data


def parse_stakes(value: Any) -> list[dict[str, Any]]:
    """モデルの買い目文字列を、重複のない3連単と金額へ正規化する。"""

    if not value:
        return []
    parsed: dict[str, float] = {}
    for match in COMBO_PATTERN.finditer(str(value)):
        lanes = match.group(1), match.group(2), match.group(3)
        if len(set(lanes)) != 3:
            continue
        combo = "-".join(lanes)
        stake = float(match.group(4)) if match.group(4) else 0.0
        parsed[combo] = max(parsed.get(combo, 0.0), stake)
    return [
        {"combo": combo, "stake_yen": int(stake) if stake.is_integer() else stake}
        for combo, stake in parsed.items()
    ]


def _metric_index(performance: dict[str, Any], period: str) -> dict[str, dict[str, Any]]:
    models = performance.get("periods", {}).get(period, {}).get("models", [])
    if not isinstance(models, list):
        return {}
    return {
        str(item.get("key")): item
        for item in models
        if isinstance(item, dict) and item.get("key")
    }


def _select_metrics(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    keys = ("n", "hits", "hit_rate", "invest", "return", "profit", "roi", "max_drawdown")
    return {key: item.get(key) for key in keys if key in item}


def _select_clv(item: dict[str, Any] | None) -> dict[str, Any]:
    if not item:
        return {}
    keys = ("status", "graded_races", "picks", "avg_clv_pp", "positive_rate_pct")
    return {key: item.get(key) for key in keys if key in item}


def _clean_boats(boats: Any) -> list[dict[str, Any]]:
    """氏名や自由記述を除き、事前に得られる数値・級別だけを残す。"""

    if not isinstance(boats, list):
        return []
    cleaned = []
    for boat in boats:
        if not isinstance(boat, dict):
            continue
        cleaned.append(
            {
                "lane": boat.get("lane"),
                "rank": boat.get("rank"),
                "win_rate": boat.get("win_rate"),
                "motor_no": boat.get("motor_no"),
                "weight": boat.get("weight"),
                "tilt": boat.get("tilt"),
                "exhibition_time": boat.get("ex_time"),
            }
        )
    return cleaned


def build_race_state(
    race: dict[str, Any],
    performance: dict[str, Any],
    clv_summary: dict[str, Any],
    *,
    source_ids: tuple[str, ...] | None = None,
    selector_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """自由形式の分析文を除外し、Jev向けの構造化stateを作る。"""

    weekly = _metric_index(performance, "weekly")
    monthly = _metric_index(performance, "monthly")
    clv_models = clv_summary.get("models", {})
    if not isinstance(clv_models, dict):
        clv_models = {}

    model_predictions = []
    candidate_models: dict[str, set[str]] = defaultdict(set)
    candidate_stakes: dict[str, float] = defaultdict(float)

    allowed_sources = set(source_ids) if source_ids is not None else None
    for source in MODEL_SOURCES:
        if allowed_sources is not None and source["id"] not in allowed_sources:
            continue
        picks = parse_stakes(race.get(source["pick_field"]))
        if not picks:
            continue
        for pick in picks:
            candidate_models[pick["combo"]].add(source["id"])
            candidate_stakes[pick["combo"]] += float(pick["stake_yen"])
        model_predictions.append(
            {
                "model_id": source["id"],
                "label": source["label"],
                "picks": picks,
                "weekly": _select_metrics(weekly.get(source["performance_key"])),
                "monthly": _select_metrics(monthly.get(source["performance_key"])),
                "clv": _select_clv(clv_models.get(source["clv_key"]))
                if source["clv_key"]
                else {},
            }
        )

    odds_map = {}
    for item in race.get("odds_top", []) if isinstance(race.get("odds_top"), list) else []:
        if isinstance(item, dict) and item.get("combo"):
            odds_map[str(item["combo"])] = item.get("odds")

    candidates = []
    for combo, models in candidate_models.items():
        candidates.append(
            {
                "combo": combo,
                "model_count": len(models),
                "models": sorted(models),
                "total_proposed_stake_yen": int(candidate_stakes[combo]),
                "odds": odds_map.get(combo),
            }
        )
    candidates.sort(
        key=lambda item: (
            -int(item["model_count"]),
            -int(item["total_proposed_stake_yen"]),
            float(item["odds"]) if item["odds"] is not None else float("inf"),
            str(item["combo"]),
        )
    )
    candidates = candidates[:MAX_CANDIDATES]

    active_model_count = len(model_predictions)
    max_vote_count = max((item["model_count"] for item in candidates), default=0)
    max_vote_ratio = round(max_vote_count / active_model_count, 4) if active_model_count else 0.0
    conditions = {
        "weather": race.get("weather") or None,
        "wind_speed": race.get("wind_speed") or None,
        "wind_direction": race.get("wind_dir") or None,
        "wave": race.get("wave") or None,
        "water_temperature": race.get("water_temp") or None,
    }

    state = {
        "purpose": "Shadow-only review. This output must not execute or authorize a wager.",
        "race": {
            "race_id": race.get("race_id"),
            "date": race.get("date"),
            "venue": race.get("venue"),
            "race_number": race.get("r"),
            "conditions": conditions,
            "boats": _clean_boats(race.get("boats")),
        },
        "model_predictions": model_predictions,
        "candidates": candidates,
        "agreement": {
            "active_model_count": active_model_count,
            "unique_candidate_count": len(candidate_models),
            "max_vote_count": max_vote_count,
            "max_vote_ratio": max_vote_ratio,
        },
        "data_quality": {
            "boat_count": len(race.get("boats", [])) if isinstance(race.get("boats"), list) else 0,
            "odds_count": len(odds_map),
            "active_model_count": active_model_count,
            "missing_condition_count": sum(value is None for value in conditions.values()),
        },
        "historical_cutoff": performance.get("latest_result_date"),
    }
    if selector_feedback:
        state["selector_history"] = selector_feedback
    return state


def _candidate_key(combo: str) -> str:
    return "candidate_" + combo.replace("-", "_")


def build_questions(
    state: dict[str, Any], *, selector_only: bool = False
) -> tuple[dict[str, Any], dict[str, str]]:
    """複数観点を混ぜず、独立した短い質問として定義する。"""

    candidate_map = {"no_candidate": ""}
    candidate_criteria: dict[str, Any] = {
        "no_candidate": "No candidate has sufficient pre-race support for a shadow selection."
    }
    for candidate in state.get("candidates", []):
        combo = str(candidate["combo"])
        key = _candidate_key(combo)
        candidate_map[key] = combo
        candidate_criteria[key] = candidate

    questions = {
        "action": {
            "type": "choice",
            "instructions": (
                "Choose the prudent shadow action using only the supplied pre-race evidence. "
                "This is an evaluation label, not permission to wager. Prefer skip when odds, "
                "data completeness, model history, or cross-model support are weak."
            ),
            "criteria": {
                "skip": "Do not select a wager in shadow evaluation.",
                "small": "Record only a small hypothetical exposure for comparison.",
                "standard": "Record a normal hypothetical exposure for comparison.",
            },
        },
        "candidate": {
            "type": "choice",
            "instructions": (
                "Select at most one supplied candidate that has the strongest combined pre-race "
                "support and value evidence, or choose no_candidate."
            ),
            "criteria": candidate_criteria,
        },
        "data_sufficient": {
            "type": "noul",
            "instructions": (
                "The supplied pre-race data is sufficiently complete to make a meaningful shadow "
                "purchase decision, including usable odds and more than one model opinion."
            ),
        },
        "evidence_strength": {
            "type": "score",
            "instructions": "Rate the strength of the supplied evidence for making any purchase.",
            "criteria": [
                "Insufficient evidence; skip.",
                "Weak or conflicting evidence.",
                "Moderate evidence with material uncertainty.",
                "Strong and corroborated evidence.",
            ],
        },
        "variance_risk": {
            "type": "score",
            "instructions": (
                "Rate the risk that this decision is unstable or overly dependent on sparse, "
                "conflicting, or high-variance evidence."
            ),
            "criteria": [
                "Low instability risk.",
                "Moderate instability risk.",
                "High instability risk.",
                "Extreme instability risk.",
            ],
        },
    }
    if selector_only:
        # 単一モデルとの組合せでは購入可否を混ぜず、候補選択の能力だけを測る。
        questions.pop("action")
        questions["data_sufficient"]["instructions"] = (
            "The supplied pre-race data, usable odds, source-model history, and candidate set "
            "are sufficiently complete to compare the supplied candidates."
        )
    return questions, candidate_map


def validate_temporal_boundary(target_date: str, performance: dict[str, Any]) -> None:
    """対象日当日以降の結果が履歴集計へ混ざることを拒否する。"""

    latest_result_date = str(performance.get("latest_result_date") or "")
    if latest_result_date and latest_result_date >= target_date:
        raise ValueError(
            "未来情報防止: model_performanceの最新結果日が対象日より前ではありません "
            f"(latest_result_date={latest_result_date}, target_date={target_date})"
        )


def validate_experiment_temporal_boundary(
    target_date: str, experiment_performance: dict[str, Any]
) -> None:
    """Jev自身の比較成績にも対象日以降の結果が混ざっていないか確認する。"""

    latest_result_date = str(experiment_performance.get("latest_result_date") or "")
    if latest_result_date and latest_result_date >= target_date:
        raise ValueError(
            "未来情報防止: Jev比較成績の最新結果日が対象日より前ではありません "
            f"(latest_result_date={latest_result_date}, target_date={target_date})"
        )


def selector_feedback_for_arm(
    experiment_performance: dict[str, Any], arm_id: str
) -> dict[str, Any]:
    """確定済み比較成績からJevへ渡してよい少数の監査指標だけを選ぶ。"""

    arms = experiment_performance.get("arms", {})
    arm = arms.get(arm_id) if isinstance(arms, dict) else None
    if not isinstance(arm, dict):
        return {}
    selected = arm.get("forced_selected")
    if not isinstance(selected, dict):
        return {}
    allowed = (
        "purchased_races",
        "hits",
        "hit_rate_pct",
        "invest_yen",
        "profit_yen",
        "roi_pct",
        "max_drawdown_yen",
        "profit_without_largest_win_yen",
        "roi_without_largest_win_pct",
    )
    metrics = {key: selected.get(key) for key in allowed if key in selected}
    if not metrics:
        return {}
    return {
        "experiment_version": experiment_performance.get("experiment_version"),
        "latest_result_date": experiment_performance.get("latest_result_date"),
        "arm_id": arm_id,
        "forced_selected": metrics,
    }


def call_jev(
    state: dict[str, Any],
    questions: dict[str, Any],
    api_key: str,
    *,
    endpoint: str = API_ENDPOINT,
    model: str = JEV_MODEL,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """TypeSafe公式APIを呼び、回答形式を最低限検証する。"""

    body = json.dumps(
        {"state": state, "model": model, "questions": questions},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Play-Boatrace-Jev-Shadow/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise RuntimeError(f"Jev API HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Jev API接続失敗: {exc.reason}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Jev APIの応答が有効なUTF-8 JSONではありません") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Jev APIの応答がobjectではありません")
    answers = payload.get("answers")
    if not isinstance(answers, dict):
        result = payload.get("result")
        answers = result.get("answers") if isinstance(result, dict) else None
    if not isinstance(answers, dict):
        raise RuntimeError("Jev API応答にanswersがありません")
    payload["answers"] = answers
    return payload


def load_api_key() -> str:
    """環境変数からAPIキーを取得し、値はログへ出さない。"""

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if api_key or os.name != "nt":
        return api_key

    # 環境変数を追加する前から動いている親プロセスは新しい値を継承しない。
    # Windowsでは現在ユーザーの保存済み環境変数を読み直して補完する。
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as registry_key:
            value, _ = winreg.QueryValueEx(registry_key, "TYPESAFE_API_KEY")
        return str(value).strip()
    except (FileNotFoundError, OSError, TypeError):
        return ""


def run_connection_probe(args: argparse.Namespace) -> int:
    """買い目や履歴を変更せず、認証と応答形式だけを1回確認する。"""

    api_key = load_api_key()
    if not api_key:
        raise RuntimeError("TYPESAFE_API_KEYが現在の実行ユーザーから読み取れません")
    state = {
        "purpose": "Connectivity check for a shadow-only decision service.",
        "shadow_only": True,
        "authorizes_wager": False,
    }
    questions = {
        "connected": {
            "type": "noul",
            "instructions": (
                "This is a connectivity check with no wagering action. "
                "Is the supplied state explicitly marked shadow-only and non-authorizing?"
            ),
        }
    }
    response = call_jev(
        state,
        questions,
        api_key,
        endpoint=args.endpoint,
        model=args.model,
        timeout=args.timeout,
    )
    connected = response["answers"].get("connected")
    if not isinstance(connected, dict) or "noul" not in connected:
        raise RuntimeError("Jev API接続テストの応答にconnected.noulがありません")
    log(f"Jev API接続テスト成功: model={response.get('model') or args.model}")
    return 0


def _extract_choice(answer: Any) -> tuple[str, float | None]:
    if not isinstance(answer, dict):
        return "", None
    confidence = answer.get("confidence")
    return str(answer.get("choice") or ""), float(confidence) if confidence is not None else None


def make_jev_record(
    state: dict[str, Any],
    response: dict[str, Any],
    candidate_map: dict[str, str],
    *,
    experiment_id: str = "all_models_jev",
    question_version: str = QUESTION_VERSION,
) -> dict[str, Any]:
    """API応答と、その時点で使った事前情報を監査可能な形へまとめる。"""

    answers = response["answers"]
    action, action_confidence = _extract_choice(answers.get("action"))
    candidate_key, candidate_confidence = _extract_choice(answers.get("candidate"))
    selected_candidate = candidate_map.get(candidate_key, "")
    created_at = datetime.now(JST).isoformat(timespec="seconds")
    state_hash = hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "race_id": state["race"].get("race_id"),
        "date": state["race"].get("date"),
        "venue": state["race"].get("venue"),
        "race_number": state["race"].get("race_number"),
        "created_at": created_at,
        "shadow_only": True,
        "decision_source": "jev",
        "strategy_version": STRATEGY_VERSION,
        "question_version": question_version,
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_id": experiment_id,
        "jev_model": response.get("model") or JEV_MODEL,
        "input_sha256": state_hash,
        "action": action,
        "action_confidence": action_confidence,
        "selected_candidate": selected_candidate,
        "selected_candidate_confidence": candidate_confidence,
        "answers": answers,
        "agreement": state.get("agreement", {}),
        "data_quality": state.get("data_quality", {}),
        "candidate_snapshot": state.get("candidates", []),
        "historical_cutoff": state.get("historical_cutoff"),
    }


def make_rule_skip_record(
    state: dict[str, Any],
    reason: str,
    *,
    experiment_id: str = "all_models_jev",
    question_version: str = QUESTION_VERSION,
) -> dict[str, Any]:
    """明白な入力不足はAPIへ送らず、ハードルールの見送りとして区別する。"""

    return {
        "race_id": state["race"].get("race_id"),
        "date": state["race"].get("date"),
        "venue": state["race"].get("venue"),
        "race_number": state["race"].get("race_number"),
        "created_at": datetime.now(JST).isoformat(timespec="seconds"),
        "shadow_only": True,
        "decision_source": "hard_rule",
        "strategy_version": STRATEGY_VERSION,
        "question_version": question_version,
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_id": experiment_id,
        "action": "skip",
        "action_confidence": None,
        "selected_candidate": "",
        "selected_candidate_confidence": None,
        "reason": reason,
        "agreement": state.get("agreement", {}),
        "data_quality": state.get("data_quality", {}),
        "candidate_snapshot": state.get("candidates", []),
        "historical_cutoff": state.get("historical_cutoff"),
    }


def make_raw_model_record(
    state: dict[str, Any], *, experiment_id: str
) -> dict[str, Any]:
    """Jevを通さない元モデル買い目を比較用の不変レコードとして保存する。"""

    raw_picks = [
        dict(pick)
        for model in state.get("model_predictions", [])
        if isinstance(model, dict)
        for pick in model.get("picks", [])
        if isinstance(pick, dict)
    ]
    first_candidate = str(raw_picks[0].get("combo") or "") if raw_picks else ""
    state_hash = hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "race_id": state["race"].get("race_id"),
        "date": state["race"].get("date"),
        "venue": state["race"].get("venue"),
        "race_number": state["race"].get("race_number"),
        "created_at": datetime.now(JST).isoformat(timespec="seconds"),
        "shadow_only": True,
        "decision_source": "raw_model",
        "strategy_version": STRATEGY_VERSION,
        "question_version": None,
        "experiment_version": EXPERIMENT_VERSION,
        "experiment_id": experiment_id,
        "input_sha256": state_hash,
        "action": "raw_baseline",
        "selected_candidate": first_candidate,
        "raw_picks": raw_picks,
        "agreement": state.get("agreement", {}),
        "data_quality": state.get("data_quality", {}),
        "candidate_snapshot": state.get("candidates", []),
        "historical_cutoff": state.get("historical_cutoff"),
    }


def load_history(path: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    """JSONL履歴を読み込み、同じ戦略・レース・実験の再課金を防ぐ。"""

    records: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Jev履歴JSONLの{line_number}行目が壊れています: {path}") from exc
            key = (
                str(record.get("date") or ""),
                str(record.get("race_id") or ""),
                str(record.get("strategy_version") or ""),
                str(record.get("experiment_id") or "all_models_jev"),
            )
            if all(key):
                records[key] = record
    return records


def append_history(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_output(path: Path, payload: dict[str, Any]) -> None:
    """OneDrive同期中でも壊れにくいよう、一時ファイルから置換する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def build_arm_record(
    race: dict[str, Any],
    performance: dict[str, Any],
    clv_summary: dict[str, Any],
    experiment_performance: dict[str, Any],
    arm: dict[str, Any],
    args: argparse.Namespace,
    api_key: str,
) -> tuple[dict[str, Any], bool]:
    """1実験アームのレコードを作り、Jev APIを呼んだかも返す。"""

    arm_id = str(arm["id"])
    arm_type = str(arm["type"])
    selector_only = arm_type == "jev_selector"
    question_version = SELECTOR_QUESTION_VERSION if selector_only else QUESTION_VERSION
    feedback = (
        selector_feedback_for_arm(experiment_performance, arm_id)
        if arm_type.startswith("jev_")
        else {}
    )
    state = build_race_state(
        race,
        performance,
        clv_summary,
        source_ids=arm.get("source_ids"),
        selector_feedback=feedback,
    )
    if arm_type == "raw_model":
        return make_raw_model_record(state, experiment_id=arm_id), False

    quality = state["data_quality"]
    if quality["odds_count"] == 0:
        return (
            make_rule_skip_record(
                state,
                "usable_odds_missing",
                experiment_id=arm_id,
                question_version=question_version,
            ),
            False,
        )
    if quality["active_model_count"] < int(arm["minimum_models"]):
        reason = (
            "source_model_prediction_missing"
            if arm.get("source_ids")
            else "fewer_than_two_active_models"
        )
        return (
            make_rule_skip_record(
                state,
                reason,
                experiment_id=arm_id,
                question_version=question_version,
            ),
            False,
        )
    if args.dry_run:
        return (
            make_rule_skip_record(
                state,
                "dry_run_no_api_call",
                experiment_id=arm_id,
                question_version=question_version,
            ),
            False,
        )

    questions, candidate_map = build_questions(state, selector_only=selector_only)
    response = call_jev(
        state,
        questions,
        api_key,
        endpoint=args.endpoint,
        model=args.model,
        timeout=args.timeout,
    )
    return (
        make_jev_record(
            state,
            response,
            candidate_map,
            experiment_id=arm_id,
            question_version=question_version,
        ),
        True,
    )


def run(args: argparse.Namespace) -> int:
    race_info = load_json(Path(args.input))
    performance = load_json(Path(args.performance), required=False)
    clv_summary = load_json(Path(args.clv), required=False)
    experiment_performance = load_json(
        Path(args.experiment_performance), required=False
    )
    target_date = str(race_info.get("date") or "")
    races = race_info.get("races")
    if not target_date or not isinstance(races, list):
        raise ValueError("daily_race_info.jsonにdateまたはracesがありません")

    today = datetime.now(JST).date().isoformat()
    if target_date != today:
        payload = {
            "date": target_date,
            "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
            "status": "skipped_historical_date",
            "shadow_only": True,
            "experiment_version": EXPERIMENT_VERSION,
            "reason": f"対象日{target_date}は本日{today}ではないため後付け判定を拒否しました",
            "decisions": [],
            "comparisons": [],
        }
        write_output(Path(args.output), payload)
        log(payload["reason"])
        return 0

    validate_temporal_boundary(target_date, performance)
    validate_experiment_temporal_boundary(target_date, experiment_performance)
    history = load_history(Path(args.history))
    existing_for_date = {
        (key[1], key[3]): record
        for key, record in history.items()
        if key[0] == target_date
        and key[2] == STRATEGY_VERSION
        and record.get("experiment_version") == EXPERIMENT_VERSION
    }

    api_key = load_api_key()
    if not api_key and not args.dry_run:
        log("TYPESAFE_API_KEYが未設定のため、Jev実験アームは既存判定だけを使用します")

    arms = (
        tuple(arm for arm in PAIRING_ARMS if arm["id"] == "all_models_jev")
        if args.no_pairing_experiments
        else PAIRING_ARMS
    )
    decisions: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    arm_stats = {
        str(arm["id"]): {
            "records": 0,
            "new": 0,
            "reused": 0,
            "errors": 0,
            "api_calls": 0,
        }
        for arm in arms
    }
    for race in races:
        if not isinstance(race, dict) or not race.get("race_id"):
            continue
        race_id = str(race["race_id"])
        comparison = {
            "race_id": race_id,
            "date": target_date,
            "arms": {},
        }
        for arm in arms:
            arm_id = str(arm["id"])
            stats = arm_stats[arm_id]
            record = existing_for_date.get((race_id, arm_id))
            if record is not None:
                stats["reused"] += 1
            else:
                if (
                    str(arm["type"]).startswith("jev_")
                    and not api_key
                    and not args.dry_run
                ):
                    stats["errors"] += 1
                    errors.append(
                        {
                            "race_id": race_id,
                            "experiment_id": arm_id,
                            "error": "TYPESAFE_API_KEYが未設定です",
                        }
                    )
                    continue
                try:
                    record, api_called = build_arm_record(
                        race,
                        performance,
                        clv_summary,
                        experiment_performance,
                        arm,
                        args,
                        api_key,
                    )
                    stats["api_calls"] += int(api_called)
                    stats["new"] += 1
                    if not args.dry_run:
                        append_history(Path(args.history), record)
                except Exception as exc:  # 入力不正やAPI障害を実験アーム単位で分離する
                    stats["errors"] += 1
                    errors.append(
                        {
                            "race_id": race_id,
                            "experiment_id": arm_id,
                            "error": str(exc)[:500],
                        }
                    )
                    log(f"[WARN] {race_id}/{arm_id}: Jev処理に失敗しました: {exc}")
                    continue

            stats["records"] += 1
            comparison["arms"][arm_id] = record
            if arm_id == "all_models_jev":
                decisions.append(record)
        comparisons.append(comparison)

    all_stats = arm_stats.get(
        "all_models_jev",
        {"new": 0, "reused": 0, "api_calls": 0},
    )
    if args.dry_run:
        status = "dry_run"
    elif not api_key:
        status = "disabled_missing_api_key"
    else:
        status = "partial" if errors else "ok"
    payload = {
        "date": target_date,
        "generated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "status": status,
        "shadow_only": True,
        "strategy_version": STRATEGY_VERSION,
        "question_version": QUESTION_VERSION,
        "selector_question_version": SELECTOR_QUESTION_VERSION,
        "experiment_version": EXPERIMENT_VERSION,
        "summary": {
            "races_in_input": len(races),
            "decisions": len(decisions),
            "new_decisions": all_stats["new"],
            "reused_decisions": all_stats["reused"],
            "api_calls": sum(item["api_calls"] for item in arm_stats.values()),
            "errors": len(errors),
        },
        "experiment_summary": {
            "enabled": not args.no_pairing_experiments,
            "arms": arm_stats,
        },
        "decisions": decisions,
        "comparisons": comparisons,
        "errors": errors,
    }
    write_output(Path(args.output), payload)
    log(
        f"Jevシャドー判定完了: {len(decisions)}件 "
        f"(全モデル新規{all_stats['new']} / 再利用{all_stats['reused']} / "
        f"API合計{payload['summary']['api_calls']} / エラー{len(errors)})"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jevによるボートレース購入判断のシャドー記録")
    parser.add_argument("--input", default=str(DEFAULT_RACE_INFO))
    parser.add_argument("--performance", default=str(DEFAULT_PERFORMANCE))
    parser.add_argument("--clv", default=str(DEFAULT_CLV))
    parser.add_argument(
        "--experiment-performance",
        default=str(DEFAULT_EXPERIMENT_PERFORMANCE),
        help="前日までのJev組合せ比較成績JSON",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    parser.add_argument("--endpoint", default=API_ENDPOINT)
    parser.add_argument("--model", default=JEV_MODEL)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="APIを呼ばず、入力検証とハードルール判定だけを実行する",
    )
    parser.add_argument(
        "--no-pairing-experiments",
        action="store_true",
        help="Codex/Claudeとの組合せ実験を無効にし、全モデルJevだけを記録する",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="買い目や履歴を変更せず、TypeSafe APIへの接続だけを確認する",
    )
    return parser.parse_args(argv)


def main() -> int:
    try:
        args = parse_args()
        if args.probe:
            return run_connection_probe(args)
        return run(args)
    except Exception as exc:
        log(f"[ERROR] Jevシャドー判定を中止しました: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
