"""モデル別予測へ渡す過去実績・類似レース学習コンテキストを生成する。"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


COMBO_PATTERN = re.compile(r"^[1-6]-[1-6]-[1-6]$")
NUMBER_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")
LEARNING_STRATEGY_VERSION = "feedback_v2_model_isolated"

# 自己評価はモデルごとの予測だけを参照する。共通の過去レース結果は
# 全モデルで共有するが、他モデルの買い目はフィードバックへ混ぜない。
MODEL_PREDICTION_CONFIGS = {
    "codex": {
        "file": "daily_codex_predictions.csv",
        "stakes": "Stakes_Codex",
        "strategy": "Strategy_Codex",
        "label": "Codex",
    },
    "claude": {
        "file": "daily_claude_predictions.csv",
        "stakes": "Stakes_Claude",
        "strategy": "Strategy_Claude",
        "label": "Claude",
    },
    "gemini": {
        "file": "daily_gemini_predictions.csv",
        "stakes": "Stakes_Gemini",
        "strategy": "Strategy_Gemini",
        "label": "Gemini",
    },
    "grok": {
        "file": "daily_grok_predictions.csv",
        "stakes": "Stakes_Grok",
        "strategy": "Strategy_Grok",
        "label": "Grok",
    },
}


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def extract_number(value: Any) -> float | None:
    """`3m` や `5cm` から比較用の数値だけを取り出す。"""
    match = NUMBER_PATTERN.search(str(value or ""))
    return safe_float(match.group(0)) if match else None


def race_band(race_number: Any) -> str:
    number = int(safe_float(race_number, 0) or 0)
    if number <= 4:
        return "early"
    if number <= 8:
        return "middle"
    return "late"


def condition_bucket(value: float | None, first_limit: float, second_limit: float) -> str:
    if value is None:
        return "unknown"
    if value <= first_limit:
        return "low"
    if value <= second_limit:
        return "middle"
    return "high"


def normalize_result(value: Any) -> str:
    digits = re.findall(r"[1-6]", str(value or ""))
    combo = "-".join(digits[:3])
    if not COMBO_PATTERN.fullmatch(combo) or len(set(digits[:3])) != 3:
        return ""
    return combo


def boat_profile(boats: Iterable[dict[str, Any]]) -> dict[str, Any]:
    win_rates: dict[int, float] = {}
    ranks: dict[int, str] = {}
    for boat in boats:
        lane = int(safe_float(boat.get("lane", boat.get("Lane")), 0) or 0)
        if not 1 <= lane <= 6:
            continue
        rate = safe_float(boat.get("win_rate", boat.get("WinRate")))
        if rate is not None:
            win_rates[lane] = rate
        ranks[lane] = str(boat.get("rank", boat.get("Rank", "")) or "")

    lane1_rate = win_rates.get(1)
    top_lane = max(win_rates, key=win_rates.get) if win_rates else 0
    top_rate = win_rates.get(top_lane) if top_lane else None
    if lane1_rate is None or top_rate is None:
        lane1_strength = "unknown"
        lane1_gap = None
    else:
        lane1_gap = round(lane1_rate - top_rate, 2)
        if lane1_gap >= -0.3:
            lane1_strength = "strong"
        elif lane1_gap >= -1.0:
            lane1_strength = "middle"
        else:
            lane1_strength = "weak"

    return {
        "win_rates": win_rates,
        "ranks": ranks,
        "lane1_rate": lane1_rate,
        "top_lane": top_lane,
        "lane1_gap": lane1_gap,
        "lane1_strength": lane1_strength,
    }


def load_history_records(data_dir: Path, target_date: str) -> list[dict[str, Any]]:
    """予測日より前だけを読み込み、未来情報の混入を防ぐ。"""
    history_path = data_dir / "daily_history_results.csv"
    race_path = data_dir / "daily_raw_race_data.csv"
    before_path = data_dir / "daily_raw_beforeinfo.csv"
    if not history_path.is_file() or not race_path.is_file():
        return []

    results: dict[str, dict[str, Any]] = {}
    with history_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            date = str(row.get("Date", ""))
            race_id = str(row.get("ID", "")).strip()
            result = normalize_result(row.get("Result"))
            if race_id and result and date and date < target_date:
                results[race_id] = {
                    "race_id": race_id,
                    "date": date,
                    "venue": str(row.get("Venue", "")),
                    "r": int(safe_float(row.get("R"), 0) or 0),
                    "result": result,
                    "payout": safe_float(row.get("Payout"), 0) or 0,
                }

    boats_by_race: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with race_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID", "")).strip()
            if race_id in results:
                boats_by_race[race_id].append(row)

    before_by_race: dict[str, dict[str, Any]] = {}
    if before_path.is_file():
        with before_path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                race_id = str(row.get("ID", "")).strip()
                if race_id in results:
                    before_by_race[race_id] = row

    records: list[dict[str, Any]] = []
    for race_id, result_row in results.items():
        boats = boats_by_race.get(race_id, [])
        if len(boats) < 4:
            continue
        profile = boat_profile(boats)
        before = before_by_race.get(race_id, {})
        wind = extract_number(before.get("WindSpeed"))
        wave = extract_number(before.get("Wave"))
        records.append({
            **result_row,
            **profile,
            "race_band": race_band(result_row["r"]),
            "wind_bucket": condition_bucket(wind, 2, 5),
            "wave_bucket": condition_bucket(wave, 2, 5),
        })
    return records


def target_features(race: dict[str, Any]) -> dict[str, Any]:
    profile = boat_profile(race.get("boats", []))
    wind = extract_number(race.get("wind_speed"))
    wave = extract_number(race.get("wave"))
    return {
        "venue": str(race.get("venue", "")),
        "r": int(safe_float(race.get("r"), 0) or 0),
        **profile,
        "race_band": race_band(race.get("r")),
        "wind_bucket": condition_bucket(wind, 2, 5),
        "wave_bucket": condition_bucket(wave, 2, 5),
    }


def similarity_score(target: dict[str, Any], record: dict[str, Any]) -> float:
    score = 0.0
    if target["venue"] and target["venue"] == record["venue"]:
        score += 5.0
    if target["race_band"] == record["race_band"]:
        score += 1.0
    if target["lane1_strength"] == record["lane1_strength"] != "unknown":
        score += 2.5
    if target["top_lane"] and target["top_lane"] == record["top_lane"]:
        score += 1.5
    if target["wind_bucket"] == record["wind_bucket"] != "unknown":
        score += 0.75
    if target["wave_bucket"] == record["wave_bucket"] != "unknown":
        score += 0.75
    if target["lane1_gap"] is not None and record["lane1_gap"] is not None:
        score += max(0.0, 1.5 - abs(target["lane1_gap"] - record["lane1_gap"]))
    return round(score, 3)


def summarize_records(records: list[dict[str, Any]], examples: int = 0) -> dict[str, Any]:
    if not records:
        return {"sample_count": 0}
    winner_counts = Counter(row["result"].split("-")[0] for row in records)
    combo_counts = Counter(row["result"] for row in records)
    lane1_top3 = sum("1" in row["result"].split("-") for row in records)
    total = len(records)
    summary: dict[str, Any] = {
        "sample_count": total,
        "winner_lane_rates_pct": {
            str(lane): round(winner_counts[str(lane)] / total * 100, 1)
            for lane in range(1, 7)
        },
        "lane1_top3_rate_pct": round(lane1_top3 / total * 100, 1),
        "top_results": [
            {"combo": combo, "count": count, "rate_pct": round(count / total * 100, 1)}
            for combo, count in combo_counts.most_common(5)
        ],
    }
    if examples:
        summary["closest_examples"] = [
            {
                "date": row["date"],
                "venue": row["venue"],
                "r": row["r"],
                "lane1_strength": row["lane1_strength"],
                "actual_result": row["result"],
                "payout": round(row["payout"]),
            }
            for row in records[:examples]
        ]
    return summary


def build_similar_summary(race: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    target = target_features(race)
    scored = [
        (similarity_score(target, record), record)
        for record in records
    ]
    scored.sort(key=lambda item: (item[0], item[1]["date"]), reverse=True)
    # 会場一致など最低限の類似性がある上位60件だけを統計に使う。
    selected = [record for score, record in scored if score >= 3.0][:60]
    if len(selected) < 20:
        selected = [record for _, record in scored[:60]]
    summary = summarize_records(selected, examples=3)
    summary["target_profile"] = {
        "race_band": target["race_band"],
        "lane1_strength": target["lane1_strength"],
        "top_win_rate_lane": target["top_lane"],
        "wind_bucket": target["wind_bucket"],
        "wave_bucket": target["wave_bucket"],
    }
    return summary


def parse_stakes(value: Any) -> list[tuple[str, float]]:
    picks: list[tuple[str, float]] = []
    for part in str(value or "").split(","):
        combo, separator, stake_text = part.strip().partition(":")
        stake = safe_float(stake_text, 0) or 0
        if separator and normalize_result(combo) == combo and stake > 0:
            picks.append((combo, stake))
    return picks


def model_feedback(
    data_dir: Path,
    target_date: str,
    records: list[dict[str, Any]],
    model_key: str,
) -> dict[str, Any]:
    """対象モデル自身の、予測日より前に確定した成績だけを集計する。"""
    config = MODEL_PREDICTION_CONFIGS.get(model_key)
    if not config:
        raise ValueError(f"未対応のフィードバックモデルです: {model_key}")
    prediction_path = data_dir / config["file"]
    if not prediction_path.is_file():
        return {
            "model_key": model_key,
            "model_label": config["label"],
            "settled_count": 0,
            "status": f"no_{model_key}_results_yet",
        }
    record_by_id = {row["race_id"]: row for row in records}
    settled: list[dict[str, Any]] = []
    with prediction_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("Date", "")) >= target_date:
                continue
            record = record_by_id.get(str(row.get("RaceID", "")))
            picks = parse_stakes(row.get(config["stakes"]))
            if not record or not picks:
                continue
            actual = record["result"]
            hit_stake = sum(stake for combo, stake in picks if combo == actual)
            investment = sum(stake for _, stake in picks)
            predicted_winners = {combo.split("-")[0] for combo, _ in picks}
            settled.append({
                "race_id": record["race_id"],
                "date": record["date"],
                "venue": record["venue"],
                "actual": actual,
                "picks": [combo for combo, _ in picks],
                "hit": hit_stake > 0,
                "investment": investment,
                "return": hit_stake * record["payout"] / 100,
                "actual_winner_covered": actual.split("-")[0] in predicted_winners,
                "strategy": str(row.get(config["strategy"], "")).strip() or "legacy",
            })

    settled.sort(key=lambda row: (row["date"], row["race_id"]))

    def period_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {"races": 0, "hits": 0, "hit_rate_pct": 0, "roi_pct": 0}
        investment = sum(row["investment"] for row in rows)
        returns = sum(row["return"] for row in rows)
        hits = sum(row["hit"] for row in rows)
        return {
            "races": len(rows),
            "hits": hits,
            "hit_rate_pct": round(hits / len(rows) * 100, 1),
            "roi_pct": round(returns / investment * 100, 1) if investment else 0,
        }

    missed_winner_lanes = Counter(
        row["actual"].split("-")[0]
        for row in settled
        if not row["actual_winner_covered"]
    )
    recent_misses = [
        {"race_id": row["race_id"], "predicted": row["picks"], "actual": row["actual"]}
        for row in reversed(settled)
        if not row["hit"]
    ][:5]
    count = len(settled)
    by_strategy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in settled:
        by_strategy[row["strategy"]].append(row)
    return {
        "model_key": model_key,
        "model_label": config["label"],
        "settled_count": count,
        "status": "preliminary" if count < 200 else "established",
        "all_time": period_summary(settled),
        "recent_50": period_summary(settled[-50:]),
        "strategy_comparison": {
            strategy: period_summary(rows)
            for strategy, rows in sorted(by_strategy.items())
        },
        "actual_winner_not_covered_by_lane": dict(sorted(missed_winner_lanes.items())),
        "recent_misses": recent_misses,
        "caution": f"{config['label']}固有データが200件未満の間は、失敗傾向を参考値として扱い過学習しない。" if count < 200 else "直近50件と全期間の両方を確認し、短期変動へ過剰反応しない。",
    }


def codex_feedback(data_dir: Path, target_date: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """既存呼び出しとの互換用。"""
    return model_feedback(data_dir, target_date, records, "codex")


def build_codex_learning_context(
    data_dir: Path,
    target_date: str,
    races: list[dict[str, Any]],
) -> dict[str, Any]:
    context = build_model_learning_context(data_dir, target_date, races, "codex")
    # 既存CSV列と診断JSONが参照しているキーを残す。
    context["codex_feedback"] = context["model_feedback"]
    return context


def build_model_learning_context(
    data_dir: Path,
    target_date: str,
    races: list[dict[str, Any]],
    model_key: str,
) -> dict[str, Any]:
    """共通履歴と、指定モデル自身の成績を組み合わせる。"""
    if model_key not in MODEL_PREDICTION_CONFIGS:
        raise ValueError(f"未対応のフィードバックモデルです: {model_key}")
    records = load_history_records(data_dir, target_date)
    global_summary = summarize_records(records)
    per_race = {
        str(race.get("race_id", "")): build_similar_summary(race, records)
        for race in races
        if str(race.get("race_id", ""))
    }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "target_date": target_date,
        "strategy_version": LEARNING_STRATEGY_VERSION,
        "leakage_guard": f"Only races dated before {target_date} were used.",
        "historical_results_used": len(records),
        "global_baseline": global_summary,
        "model_key": model_key,
        "model_feedback": model_feedback(data_dir, target_date, records, model_key),
        "races": per_race,
    }


def learning_context_for_prompt(context: dict[str, Any], race_ids: set[str]) -> dict[str, Any]:
    """入力トークンを抑えるため、予測対象レースの学習情報だけに絞る。"""
    return {
        "target_date": context.get("target_date"),
        "strategy_version": context.get("strategy_version", LEARNING_STRATEGY_VERSION),
        "leakage_guard": context.get("leakage_guard"),
        "historical_results_used": context.get("historical_results_used", 0),
        "global_baseline": context.get("global_baseline", {}),
        "model_key": context.get("model_key", "codex"),
        "model_feedback": context.get("model_feedback", context.get("codex_feedback", {})),
        "races": {
            race_id: context.get("races", {}).get(race_id, {})
            for race_id in race_ids
        },
    }


def save_learning_context(path: Path, context: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(context, handle, ensure_ascii=False, indent=2)
