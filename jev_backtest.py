"""保存済みの予測だけを使い、Jev購入ゲートを時系列バックテストする。

各対象レースより前に確定していた成績・CLVだけを再構成し、結果や払戻は
Jev判定が終わった後の採点にだけ使用する。既存の予測、実購入、公開JSONは
変更しない。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import jev_shadow
import model_performance


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


ROOT = Path(__file__).resolve().parent
DAILY = ROOT / "daily_data"
PUBLIC = ROOT / "dashboard" / "public" / "daily_data"

DEFAULT_PREDICTIONS = PUBLIC / "ai_predictions_summary.json"
DEFAULT_RESULTS = PUBLIC / "daily_history_results.csv"
DEFAULT_RACE_DATA = DAILY / "daily_raw_race_data.csv"
DEFAULT_BEFOREINFO = DAILY / "daily_raw_beforeinfo.csv"
DEFAULT_MORNING_ODDS = DAILY / "daily_odds_3t.csv"
DEFAULT_CLOSING_ODDS = DAILY / "closing_odds_3t.csv"
DEFAULT_CLV_LOG = DAILY / "clv_prediction_log.csv"
DEFAULT_HISTORY = DAILY / "jev_backtest_git_decisions.jsonl"
DEFAULT_OUTPUT = ROOT / "reports" / "jev_backtest_git_summary.json"

GIT_RACE_INFO = "dashboard/public/daily_data/daily_race_info.json"
GIT_PERFORMANCE = "dashboard/public/daily_data/model_performance.json"
GIT_CLV_SUMMARY = "dashboard/public/daily_data/clv_summary.json"

SUMMARY_TO_PICK = {
    "stakes": "ai_picks_llm",
    "stakes_gemini": "ai_picks_gemini",
    "stakes_grok": "ai_picks_grok",
    "stakes_gemmaft": "ai_picks_gemmaft",
    "stakes_gemmaclaude": "ai_picks_gemmaclaude",
    "stakes_gemmagrokx": "ai_picks_gemmagrokx",
    "stakes_codex": "ai_picks_codex",
    "stakes_claude": "ai_picks_claude",
}

CLV_LABELS = {
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
    "grok": "Grok",
    "gemma": "Gemma弟子",
    "gemma_claude": "Qwen弟子(Claude先生)",
    "gemma_grok_x": "Qwen弟子(Grok+X先生)",
}
MIN_CLV_RACES_ACTIVE = 30


def load_json(path: Path) -> dict[str, Any]:
    """JSON objectを読み込み、形式不正なら明示的に停止する。"""

    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON objectではありません: {path}")
    return payload


def normalize_combo(value: Any) -> str:
    """3連単を ``1-2-3`` 形式へ正規化する。"""

    digits = [char for char in str(value or "") if char.isdigit()]
    if len(digits) < 3 or len(set(digits[:3])) != 3:
        return ""
    return "-".join(digits[:3])


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    """重複時は末尾の結果を採用する。"""

    results: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID") or row.get("RaceID") or "").strip()
            combo = normalize_combo(row.get("Result"))
            if not race_id or not combo:
                continue
            try:
                payout = float(row.get("Payout") or 0)
            except (TypeError, ValueError):
                payout = 0.0
            results[race_id] = {
                "race_id": race_id,
                "date": str(row.get("Date") or "").strip(),
                "venue": str(row.get("Venue") or "").strip(),
                "race_number": int(float(row.get("R") or 0)),
                "result": combo,
                "payout": payout,
            }
    return results


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    """小規模な履歴CSVを標準ライブラリだけで読む。"""

    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_odds_for_races(
    path: Path, race_ids: set[str]
) -> dict[str, dict[str, float]]:
    """大きなオッズCSVから必要なレースだけをストリーム抽出する。"""

    output: dict[str, dict[str, float]] = {}
    if not path.exists() or not race_ids:
        return output
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID") or "")
            if race_id not in race_ids:
                continue
            combo = normalize_combo(row.get("Combination"))
            odd = _safe_float(row.get("Odds"))
            if combo and odd is not None and odd > 0:
                output.setdefault(race_id, {})[combo] = odd
    return output


def active_model_count(prediction: dict[str, Any]) -> int:
    """Jevが利用するモデルのうち、有効な買い目を持つ数を返す。"""

    return sum(
        bool(jev_shadow.parse_stakes(prediction.get(summary_key)))
        for summary_key in SUMMARY_TO_PICK
    )


def active_model_count_from_race(race: dict[str, Any]) -> int:
    """当時のレーススナップショットに有効なモデルが何者いるか数える。"""

    return sum(
        bool(jev_shadow.parse_stakes(race.get(source["pick_field"])))
        for source in jev_shadow.MODEL_SOURCES
    )


def state_sha256(state: dict[str, Any]) -> str:
    """Jev本体と同じ規則で入力stateのハッシュを計算する。"""

    encoded = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_ids(
    predictions: dict[str, Any],
    results: dict[str, dict[str, Any]],
    start: str,
    end: str,
) -> list[str]:
    """結果・期間・2モデル以上の条件を満たすレースを列挙する。"""

    output = []
    for race_id, result in results.items():
        race_date = str(result.get("date") or "")
        prediction = predictions.get(race_id)
        if not start <= race_date <= end or not isinstance(prediction, dict):
            continue
        if active_model_count(prediction) < jev_shadow.MIN_ACTIVE_MODELS:
            continue
        output.append(race_id)
    return sorted(output, key=lambda item: (results[item]["date"], item))


def load_boats(path: Path, race_ids: set[str]) -> dict[str, list[dict[str, Any]]]:
    """対象レースだけの出走表を読み込む。氏名は保持しない。"""

    boats: dict[str, list[dict[str, Any]]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID") or "")
            if race_id not in race_ids:
                continue
            try:
                lane = int(float(row.get("Lane") or 0))
            except (TypeError, ValueError):
                continue
            boats.setdefault(race_id, []).append(
                {
                    "lane": lane,
                    "motor_no": str(row.get("Motor") or ""),
                    "rank": str(row.get("Rank") or ""),
                    "win_rate": _safe_float(row.get("WinRate")),
                    "weight": None,
                    "tilt": None,
                    "ex_time": None,
                }
            )
    for rows in boats.values():
        rows.sort(key=lambda item: item["lane"])
    return boats


def load_beforeinfo(path: Path, race_ids: set[str]) -> dict[str, dict[str, Any]]:
    """対象レースの直前情報を読み込み、艇別項目を扱いやすい形にする。"""

    before: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return before
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID") or "")
            if race_id not in race_ids:
                continue
            item: dict[str, Any] = {
                "weather": str(row.get("Weather") or ""),
                "wind_speed": str(row.get("WindSpeed") or ""),
                "wind_dir": str(row.get("WindDir") or ""),
                "wave": str(row.get("Wave") or ""),
                "water_temp": str(row.get("WaterTemp") or ""),
                "boats": {},
            }
            for lane in range(1, 7):
                item["boats"][lane] = {
                    "weight": str(row.get(f"B{lane}_Weight") or ""),
                    "tilt": _safe_float(row.get(f"B{lane}_Tilt")),
                    "ex_time": _safe_float(row.get(f"B{lane}_ExTime")),
                }
            before[race_id] = item
    return before


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def make_race(
    race_id: str,
    prediction: dict[str, Any],
    result: dict[str, Any],
    boats_by_race: dict[str, list[dict[str, Any]]],
    before_by_race: dict[str, dict[str, Any]],
    morning_odds: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """通常運用と同じ構造のJev入力用レースを再構成する。"""

    before = before_by_race.get(race_id, {})
    boats = [dict(item) for item in boats_by_race.get(race_id, [])]
    for boat in boats:
        lane_info = before.get("boats", {}).get(boat["lane"], {})
        boat.update(lane_info)
    odds = morning_odds.get(race_id, {})
    odds_top = [
        {"combo": combo, "odds": odd}
        for combo, odd in sorted(odds.items(), key=lambda item: item[1])[:20]
    ]
    race: dict[str, Any] = {
        "race_id": race_id,
        "date": result["date"],
        "venue": result["venue"],
        "r": result["race_number"],
        "weather": before.get("weather", ""),
        "wind_speed": before.get("wind_speed", ""),
        "wind_dir": before.get("wind_dir", ""),
        "wave": before.get("wave", ""),
        "water_temp": before.get("water_temp", ""),
        "boats": boats,
        "odds_top": odds_top,
    }
    for summary_key, pick_field in SUMMARY_TO_PICK.items():
        race[pick_field] = prediction.get(summary_key, "")
    return race


def performance_snapshot(
    records_by_model: dict[str, list[dict[str, Any]]], target_date: str
) -> dict[str, Any]:
    """対象日前日までの7日・30日成績を再計算する。"""

    target = date.fromisoformat(target_date)
    cutoff = (target - timedelta(days=1)).isoformat()
    eligible_dates = [
        row["date"]
        for rows in records_by_model.values()
        for row in rows
        if row["date"] <= cutoff
    ]
    periods: dict[str, Any] = {}
    for key, days in (("weekly", 7), ("monthly", 30)):
        start = (target - timedelta(days=days)).isoformat()
        model_rows = []
        for model in model_performance.MODELS:
            records = [
                row
                for row in records_by_model[model["key"]]
                if start <= row["date"] <= cutoff
            ]
            model_rows.append({**model, **model_performance._metrics(records)})
        periods[key] = {"start_date": start, "end_date": cutoff, "models": model_rows}
    return {
        "latest_result_date": max(eligible_dates) if eligible_dates else "",
        "periods": periods,
    }


def clv_snapshot(
    prediction_log: list[dict[str, str]],
    morning_all: dict[str, dict[str, float]],
    closing_all: dict[str, dict[str, float]],
    target_date: str,
) -> dict[str, Any]:
    """対象日前日までに確定できたCLVだけを集計する。"""

    grouped: dict[str, list[dict[str, str]]] = {}
    for row in prediction_log:
        if str(row.get("Date") or "") >= target_date:
            continue
        grouped.setdefault(str(row.get("model") or ""), []).append(row)

    summary: dict[str, Any] = {}
    for model, rows in grouped.items():
        per_pick: list[float] = []
        race_averages: list[float] = []
        for row in rows:
            race_id = str(row.get("RaceID") or "")
            morning = morning_all.get(race_id, {})
            closing = closing_all.get(race_id, {})
            picks = [normalize_combo(item) for item in str(row.get("combos") or "").split(",")]
            values = clv_for_race([item for item in picks if item], morning, closing)
            if not values:
                continue
            per_pick.extend(values)
            race_averages.append(sum(values) / len(values))
        graded_races = len(race_averages)
        if not graded_races:
            summary[model] = {
                "label": CLV_LABELS.get(model, model),
                "status": "accruing",
                "graded_races": 0,
            }
            continue
        summary[model] = {
            "label": CLV_LABELS.get(model, model),
            "status": "active" if graded_races >= MIN_CLV_RACES_ACTIVE else "accruing",
            "graded_races": graded_races,
            "picks": len(per_pick),
            "avg_clv_pp": round(sum(race_averages) / graded_races, 3),
            "positive_rate_pct": round(
                sum(value > 0 for value in per_pick) / len(per_pick) * 100, 1
            ),
        }
    return {"models": summary}


def clv_for_race(
    picks: list[str],
    morning: dict[str, float],
    closing: dict[str, float],
) -> list[float]:
    """朝と締切の正規化インプライド確率差を買い目ごとに返す。"""

    common = set(morning) & set(closing)
    if len(common) < 3:
        return []
    morning_raw = {combo: 1.0 / morning[combo] for combo in common}
    closing_raw = {combo: 1.0 / closing[combo] for combo in common}
    morning_sum = sum(morning_raw.values())
    closing_sum = sum(closing_raw.values())
    if morning_sum <= 0 or closing_sum <= 0:
        return []
    return [
        (closing_raw[combo] / closing_sum - morning_raw[combo] / morning_sum) * 100
        for combo in picks
        if combo in common
    ]


def select_evenly(items: list[str], maximum: int) -> list[str]:
    """期間全体から偏りなく上限件数を抽出する。"""

    if maximum <= 0 or len(items) <= maximum:
        return items
    if maximum == 1:
        return [items[len(items) // 2]]
    indexes = [round(index * (len(items) - 1) / (maximum - 1)) for index in range(maximum)]
    return [items[index] for index in indexes]


def load_backtest_history(path: Path) -> dict[str, dict[str, Any]]:
    """中断再開用の履歴をrace_id単位で読む。"""

    output: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return output
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            race_id = str(row.get("race_id") or "") if isinstance(row, dict) else ""
            if race_id:
                output[race_id] = row
    return output


def append_history(path: Path, record: dict[str, Any]) -> None:
    """API応答後に1件ずつ保存し、中断時の二重課金を防ぐ。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def portfolio_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    """全モデルの提案を別口として維持した基準ポートフォリオを返す。"""

    return [
        pick
        for model in state.get("model_predictions", [])
        for pick in model.get("picks", [])
        if isinstance(pick, dict)
    ]


def grade_picks(picks: list[dict[str, Any]], result: str, payout: float) -> dict[str, Any]:
    """結果はJev判定後にだけ渡し、投資・払戻・収支を計算する。"""

    invest = sum(float(pick.get("stake_yen") or 0) for pick in picks)
    returned = sum(
        float(pick.get("stake_yen") or 0) * payout / 100
        for pick in picks
        if pick.get("combo") == result
    )
    return {
        "invest": round(invest),
        "return": round(returned),
        "profit": round(returned - invest),
        "hit": returned > 0,
    }


def evaluate_record(
    decision: dict[str, Any], state: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """ゲート判断と候補選択を分離し、同じ結果で採点する。"""

    baseline_picks = portfolio_from_state(state)
    baseline = grade_picks(baseline_picks, result["result"], result["payout"])
    action = str(decision.get("action") or "skip")
    gate_picks = baseline_picks if action in {"small", "standard"} else []
    gate = grade_picks(gate_picks, result["result"], result["payout"])

    selected_combo = str(decision.get("selected_candidate") or "")
    selected_stake = 0
    for candidate in decision.get("candidate_snapshot", []):
        if candidate.get("combo") == selected_combo:
            selected_stake = float(candidate.get("total_proposed_stake_yen") or 0)
            break
    selected_picks = (
        [{"combo": selected_combo, "stake_yen": selected_stake}]
        if action in {"small", "standard"} and selected_combo and selected_stake > 0
        else []
    )
    selected = grade_picks(selected_picks, result["result"], result["payout"])
    forced_selected_picks = (
        [{"combo": selected_combo, "stake_yen": selected_stake}]
        if selected_combo and selected_stake > 0
        else []
    )
    forced_selected = grade_picks(
        forced_selected_picks, result["result"], result["payout"]
    )

    state_candidates = state.get("candidates", [])
    consensus = state_candidates[0] if state_candidates else {}
    consensus_combo = str(consensus.get("combo") or "")
    consensus_stake = float(consensus.get("total_proposed_stake_yen") or 0)
    consensus_picks = (
        [{"combo": consensus_combo, "stake_yen": consensus_stake}]
        if consensus_combo and consensus_stake > 0
        else []
    )
    consensus_result = grade_picks(
        consensus_picks, result["result"], result["payout"]
    )

    probabilities = (
        decision.get("answers", {}).get("action", {}).get("probabilities", {})
    )
    try:
        buy_probability = float(probabilities.get("small") or 0) + float(
            probabilities.get("standard") or 0
        )
    except (TypeError, ValueError):
        buy_probability = 0.0
    return {
        "race_id": result["race_id"],
        "date": result["date"],
        "action": action,
        "buy_probability": round(buy_probability, 6),
        "selected_candidate": selected_combo,
        "consensus_candidate": consensus_combo,
        "baseline": baseline,
        "jev_gate": gate,
        "jev_selected": selected,
        "jev_candidate_forced": forced_selected,
        "consensus_candidate_forced": consensus_result,
        "result": result["result"],
        "payout": result["payout"],
    }


def metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """方式別の収支、ROI、的中率、最大ドローダウンを計算する。"""

    graded = [row[key] for row in rows]
    invest = sum(row["invest"] for row in graded)
    returned = sum(row["return"] for row in graded)
    hits = sum(bool(row["hit"]) for row in graded)
    purchased = sum(row["invest"] > 0 for row in graded)
    equity = peak = max_drawdown = 0
    for row in graded:
        equity += row["profit"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    positive = sorted((row["profit"] for row in graded if row["profit"] > 0), reverse=True)
    largest_win = positive[0] if positive else 0
    return_without_largest = returned - largest_win if largest_win else returned
    return {
        "races": len(graded),
        "purchased_races": purchased,
        "hits": hits,
        "hit_rate_pct": round(hits / purchased * 100, 1) if purchased else None,
        "invest_yen": round(invest),
        "return_yen": round(returned),
        "profit_yen": round(returned - invest),
        "roi_pct": round(returned / invest * 100, 1) if invest else None,
        "max_drawdown_yen": round(max_drawdown),
        "largest_single_race_profit_yen": round(largest_win),
        "profit_without_largest_win_yen": round(return_without_largest - invest),
        "roi_without_largest_win_pct": round(return_without_largest / invest * 100, 1)
        if invest
        else None,
    }


def probability_gate_metrics(
    rows: list[dict[str, Any]], threshold: float
) -> dict[str, Any]:
    """Jevの購入側確率が閾値以上のレースだけ基準買い目を購入する。"""

    converted = []
    for row in rows:
        keep = float(row.get("buy_probability") or 0) >= threshold
        converted.append(
            {
                **row,
                "probability_gate": row["baseline"]
                if keep
                else {"invest": 0, "return": 0, "profit": 0, "hit": False},
            }
        )
    output = metrics(converted, "probability_gate")
    output["threshold"] = threshold
    return output


def paired_bootstrap_difference(
    rows: list[dict[str, Any]],
    first_key: str,
    second_key: str,
    *,
    iterations: int = 5000,
    seed: int = 20261001,
) -> dict[str, Any]:
    """同一レース内の方式差を再標本化し、収支差の不確実性を示す。"""

    if not rows:
        return {
            "races": 0,
            "profit_difference_yen": None,
            "ci95_yen": [None, None],
            "probability_first_better": None,
        }
    differences = [
        float(row[first_key]["profit"]) - float(row[second_key]["profit"])
        for row in rows
    ]
    rng = random.Random(seed)
    samples = []
    count = len(differences)
    for _ in range(iterations):
        samples.append(sum(differences[rng.randrange(count)] for _ in range(count)))
    samples.sort()
    lower = samples[int(iterations * 0.025)]
    upper = samples[min(iterations - 1, int(iterations * 0.975))]
    return {
        "races": count,
        "profit_difference_yen": round(sum(differences)),
        "ci95_yen": [round(lower), round(upper)],
        "probability_first_better": round(
            sum(value > 0 for value in samples) / iterations, 4
        ),
        "iterations": iterations,
        "seed": seed,
    }


def build_summary(rows: list[dict[str, Any]], inventory: dict[str, Any]) -> dict[str, Any]:
    """比較結果と、見送りで回避・逸失した利益をまとめる。"""

    skipped = [row for row in rows if row["action"] == "skip"]
    avoided_loss = sum(-row["baseline"]["profit"] for row in skipped if row["baseline"]["profit"] < 0)
    missed_profit = sum(row["baseline"]["profit"] for row in skipped if row["baseline"]["profit"] > 0)
    def group_summary(group_rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "races": len(group_rows),
            "metrics": {
                "baseline": metrics(group_rows, "baseline"),
                "jev_candidate_forced": metrics(group_rows, "jev_candidate_forced"),
                "consensus_candidate_forced": metrics(
                    group_rows, "consensus_candidate_forced"
                ),
            },
            "probability_gate_diagnostics": [
                probability_gate_metrics(group_rows, threshold)
                for threshold in (0.25, 0.3, 0.35)
            ],
            "paired_bootstrap": paired_bootstrap_difference(
                group_rows,
                "jev_candidate_forced",
                "consensus_candidate_forced",
            ),
        }

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "historical_walk_forward",
        "comparison_rule": {
            "baseline": "全モデルの保存済み買い目を別口で購入",
            "jev_gate": "skipは全見送り、small/standardは基準ポートフォリオを維持",
            "jev_selected": "small/standard時にJev選択買い目を提案合計額で購入",
        },
        "inventory": inventory,
        "actions": dict(Counter(row["action"] for row in rows)),
        "metrics": {
            "baseline": metrics(rows, "baseline"),
            "jev_gate": metrics(rows, "jev_gate"),
            "jev_selected": metrics(rows, "jev_selected"),
            "jev_candidate_forced": metrics(rows, "jev_candidate_forced"),
            "consensus_candidate_forced": metrics(
                rows, "consensus_candidate_forced"
            ),
        },
        "probability_gate_diagnostics": [
            probability_gate_metrics(rows, threshold)
            for threshold in (0.25, 0.3, 0.35, 0.4, 0.45, 0.5)
        ],
        "sample_groups": {
            group: group_summary(
                [row for row in rows if row.get("sample_group") == group]
            )
            for group in ("pilot", "holdout")
        },
        "paired_bootstrap": paired_bootstrap_difference(
            rows,
            "jev_candidate_forced",
            "consensus_candidate_forced",
        ),
        "skip_analysis": {
            "skipped_races": len(skipped),
            "avoided_loss_yen": round(avoided_loss),
            "missed_profit_yen": round(missed_profit),
            "net_skip_effect_yen": round(avoided_loss - missed_profit),
        },
        "rows": rows,
    }


def _git_text(arguments: list[str]) -> str:
    """シェルを介さずGitから追跡済みデータを読み取る。"""

    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        message = detail[-1] if detail else "原因不明"
        raise ValueError(f"Gitスナップショットを取得できません: {message}")
    return completed.stdout


def git_snapshot_commits(start: str, end: str) -> dict[str, dict[str, str]]:
    """各日で最後に保存された朝の対戦ダッシュボードcommitを返す。"""

    raw = _git_text(
        [
            "log",
            "--format=%H%x1f%aI%x1f%s",
            "--",
            GIT_RACE_INFO,
        ]
    )
    snapshots: dict[str, dict[str, str]] = {}
    for line in raw.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commit, timestamp, subject = parts
        if not subject.startswith("Auto-update battle dashboard:"):
            continue
        try:
            snapshot_date = datetime.fromisoformat(timestamp).date().isoformat()
        except ValueError:
            continue
        if start <= snapshot_date <= end:
            # git logは新しい順なので、同日に複数あれば最終保存を採用する。
            snapshots.setdefault(
                snapshot_date,
                {"commit": commit, "timestamp": timestamp, "subject": subject},
            )
    return snapshots


def git_load_json(commit: str, relative_path: str) -> dict[str, Any]:
    """指定commitのJSON objectを作業ツリーへ書き出さずに読む。"""

    payload = json.loads(_git_text(["show", f"{commit}:{relative_path}"]))
    if not isinstance(payload, dict):
        raise ValueError(f"Git内JSON objectの形式が不正です: {relative_path}")
    return payload


def resolve_period(args: argparse.Namespace, results: dict[str, dict[str, Any]]) -> str:
    """結果の最終日を補い、対象期間を検証する。"""

    available_end = max((row["date"] for row in results.values()), default="")
    end = args.end or available_end
    if not end:
        raise ValueError("確定結果がありません")
    try:
        start_date = date.fromisoformat(args.start)
        end_date = date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("--startと--endはYYYY-MM-DD形式で指定してください") from exc
    if start_date > end_date:
        raise ValueError("--startは--end以前の日付を指定してください")
    return end


def prepare_git_snapshots(args: argparse.Namespace) -> dict[str, Any]:
    """当日朝のGit保存状態だけで未来情報のない入力stateを準備する。"""

    results = load_results(Path(args.results))
    end = resolve_period(args, results)
    snapshots = git_snapshot_commits(args.start, end)
    result_dates = sorted(
        {
            str(row.get("date") or "")
            for row in results.values()
            if args.start <= str(row.get("date") or "") <= end
        }
    )
    missing_snapshot_dates = [item for item in result_dates if item not in snapshots]
    contexts: dict[str, dict[str, Any]] = {}
    snapshot_errors: list[dict[str, str]] = []
    snapshot_race_counts: dict[str, int] = {}

    for snapshot_date, metadata in sorted(snapshots.items()):
        commit = metadata["commit"]
        try:
            race_info = git_load_json(commit, GIT_RACE_INFO)
            performance = git_load_json(commit, GIT_PERFORMANCE)
            clv = git_load_json(commit, GIT_CLV_SUMMARY)
            if str(race_info.get("date") or "") != snapshot_date:
                raise ValueError(
                    f"daily_race_infoの日付がcommit日と不一致です: {race_info.get('date')}"
                )
            jev_shadow.validate_temporal_boundary(snapshot_date, performance)
            races = race_info.get("races", [])
            if not isinstance(races, list):
                raise ValueError("daily_race_info.racesが配列ではありません")
            accepted = 0
            for race in races:
                if not isinstance(race, dict):
                    continue
                race_id = str(race.get("race_id") or "")
                result = results.get(race_id)
                if not result or str(race.get("date") or "") != snapshot_date:
                    continue
                if active_model_count_from_race(race) < jev_shadow.MIN_ACTIVE_MODELS:
                    continue
                if not race.get("odds_top"):
                    continue
                state = jev_shadow.build_race_state(race, performance, clv)
                contexts[race_id] = {
                    "state": state,
                    "snapshot_commit": commit,
                    "snapshot_timestamp": metadata["timestamp"],
                }
                accepted += 1
            snapshot_race_counts[snapshot_date] = accepted
        except Exception as exc:
            snapshot_errors.append(
                {
                    "date": snapshot_date,
                    "commit": commit,
                    "error": str(exc)[:300],
                }
            )

    eligible_ids = sorted(
        contexts,
        key=lambda race_id: (results[race_id]["date"], race_id),
    )
    selected_ids = select_evenly(eligible_ids, args.max_races)
    selected_contexts = {race_id: contexts[race_id] for race_id in selected_ids}
    inventory = {
        "source": "git_daily_snapshots",
        "start_date": args.start,
        "end_date": end,
        "snapshot_count": len(snapshots),
        "snapshot_dates": sorted(snapshots),
        "result_dates_without_snapshot": missing_snapshot_dates,
        "snapshot_errors": snapshot_errors,
        "eligible_with_point_in_time_state": len(eligible_ids),
        "selected_for_run": len(selected_ids),
        "snapshot_race_counts": snapshot_race_counts,
        "snapshot_commits": {
            key: value["commit"] for key, value in sorted(snapshots.items())
        },
        "api_calls_required_without_resume": len(selected_ids),
    }
    return {
        "results": results,
        "ids": selected_ids,
        "contexts": selected_contexts,
        "inventory": inventory,
    }


def prepare_current_files(args: argparse.Namespace) -> dict[str, Any]:
    """比較調査用に、現在ファイルから入力を再構成する（確定評価には使わない）。"""

    predictions = load_json(Path(args.predictions))
    results = load_results(Path(args.results))
    end = resolve_period(args, results)
    ids = candidate_ids(predictions, results, args.start, end)
    race_id_set = set(ids)

    prediction_log = load_csv_rows(Path(args.clv_log))
    historical_clv_ids = {
        str(row.get("RaceID") or "")
        for row in prediction_log
        if str(row.get("Date") or "") < end
    }
    odds_ids = race_id_set | historical_clv_ids
    morning_all = load_odds_for_races(Path(args.morning_odds), odds_ids)
    closing_all = load_odds_for_races(Path(args.closing_odds), historical_clv_ids)
    ids_with_odds = [race_id for race_id in ids if morning_all.get(race_id)]
    selected_ids = select_evenly(ids_with_odds, args.max_races)
    selected_set = set(selected_ids)

    boats = load_boats(Path(args.race_data), selected_set)
    before = load_beforeinfo(Path(args.beforeinfo), selected_set)
    records_by_model, _ = model_performance.load_records(
        results_path=str(args.results), predictions_path=str(args.predictions)
    )
    inventory = {
        "source": "current_files_non_authoritative",
        "start_date": args.start,
        "end_date": end,
        "eligible_before_odds": len(ids),
        "eligible_with_morning_odds": len(ids_with_odds),
        "selected_for_run": len(selected_ids),
        "selected_with_boats": sum(race_id in boats for race_id in selected_ids),
        "selected_with_beforeinfo": sum(race_id in before for race_id in selected_ids),
        "clv_log_rows_before_end": sum(
            str(row.get("Date") or "") < end for row in prediction_log
        ),
        "api_calls_required_without_resume": len(selected_ids),
    }
    return {
        "predictions": predictions,
        "results": results,
        "ids": selected_ids,
        "boats": boats,
        "before": before,
        "morning_all": morning_all,
        "closing_all": closing_all,
        "prediction_log": prediction_log,
        "records_by_model": records_by_model,
        "inventory": inventory,
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    """APIを呼ばず、指定ソースからバックテスト対象を準備する。"""

    if args.max_races < 0:
        raise ValueError("--max-racesは0以上で指定してください")
    if args.pilot_size < 0:
        raise ValueError("--pilot-sizeは0以上で指定してください")
    source = getattr(args, "source", "git")
    if source == "git":
        return prepare_git_snapshots(args)
    if source == "current":
        return prepare_current_files(args)
    raise ValueError("--sourceはgitまたはcurrentを指定してください")


def run(args: argparse.Namespace) -> int:
    """対象件数確認、または明示上限付きのライブバックテストを実行する。"""

    prepared = prepare(args)
    inventory = prepared["inventory"]
    print(json.dumps(inventory, ensure_ascii=False, indent=2))
    if not args.live:
        print("APIは呼び出していません。--live と --max-races の指定で実判定します。")
        return 0
    if args.max_races <= 0:
        raise ValueError("一括課金防止のため、--live では --max-races を必ず指定してください")

    api_key = jev_shadow.load_api_key()
    if not api_key:
        raise ValueError("TYPESAFE_API_KEYが未設定です")
    history_path = Path(args.history)
    history = load_backtest_history(history_path)
    pilot_ids = set(prepared["ids"][: args.pilot_size])
    evaluated_rows = []
    errors = []
    reused = 0
    new_calls_attempted = 0
    new_calls_succeeded = 0
    for index, race_id in enumerate(prepared["ids"], 1):
        try:
            result = prepared["results"][race_id]
            if "contexts" in prepared:
                context = prepared["contexts"][race_id]
                state = context["state"]
                snapshot_commit = str(context.get("snapshot_commit") or "")
                snapshot_timestamp = str(context.get("snapshot_timestamp") or "")
            else:
                race = make_race(
                    race_id,
                    prepared["predictions"][race_id],
                    result,
                    prepared["boats"],
                    prepared["before"],
                    prepared["morning_all"],
                )
                performance = performance_snapshot(
                    prepared["records_by_model"], result["date"]
                )
                clv = clv_snapshot(
                    prepared["prediction_log"],
                    prepared["morning_all"],
                    prepared["closing_all"],
                    result["date"],
                )
                jev_shadow.validate_temporal_boundary(result["date"], performance)
                state = jev_shadow.build_race_state(race, performance, clv)
                snapshot_commit = ""
                snapshot_timestamp = ""

            expected_hash = state_sha256(state)
            existing = history.get(race_id)
            existing_decision = (
                existing.get("decision") if isinstance(existing, dict) else None
            )
            reusable = (
                isinstance(existing_decision, dict)
                and existing_decision.get("input_sha256") == expected_hash
                and (
                    not snapshot_commit
                    or existing.get("snapshot_commit") == snapshot_commit
                )
            )
            if reusable:
                decision = existing_decision
                reused += 1
            else:
                questions, candidate_map = jev_shadow.build_questions(state)
                new_calls_attempted += 1
                response = jev_shadow.call_jev(
                    state,
                    questions,
                    api_key,
                    endpoint=args.endpoint,
                    model=args.model,
                    timeout=args.timeout,
                )
                decision = jev_shadow.make_jev_record(state, response, candidate_map)
                new_calls_succeeded += 1
                append_history(
                    history_path,
                    {
                        "race_id": race_id,
                        "target_date": result["date"],
                        "source": inventory.get("source"),
                        "snapshot_commit": snapshot_commit,
                        "snapshot_timestamp": snapshot_timestamp,
                        "decision": decision,
                    },
                )
            evaluated = evaluate_record(decision, state, result)
            evaluated["input_sha256"] = expected_hash
            evaluated["snapshot_commit"] = snapshot_commit
            evaluated["snapshot_timestamp"] = snapshot_timestamp
            evaluated["sample_group"] = (
                "pilot" if race_id in pilot_ids else "holdout"
            )
            evaluated_rows.append(evaluated)
            print(
                f"[{index}/{len(prepared['ids'])}] {race_id}: {decision.get('action')}",
                flush=True,
            )
        except Exception as exc:
            errors.append({"race_id": race_id, "error": str(exc)[:300]})
            print(
                f"[{index}/{len(prepared['ids'])}] {race_id}: ERROR {exc}",
                flush=True,
            )

    inventory["api_calls_reused"] = reused
    inventory["api_calls_new_attempted"] = new_calls_attempted
    inventory["api_calls_new_succeeded"] = new_calls_succeeded
    inventory["errors"] = len(errors)
    summary = build_summary(evaluated_rows, inventory)
    summary["errors"] = errors
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    print(f"結果: {output_path}")
    print(json.dumps(summary["metrics"], ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jev時系列バックテスト")
    parser.add_argument(
        "--source",
        choices=("git", "current"),
        default="git",
        help="git=当日保存状態（既定）、current=現在ファイルからの参考再構成",
    )
    parser.add_argument("--start", default="2026-09-15")
    parser.add_argument("--end", default="")
    parser.add_argument("--max-races", type=int, default=0)
    parser.add_argument(
        "--pilot-size",
        type=int,
        default=30,
        help="履歴先頭からパイロット扱いする件数",
    )
    parser.add_argument("--live", action="store_true", help="実際にJev APIを呼ぶ")
    parser.add_argument("--predictions", default=str(DEFAULT_PREDICTIONS))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--race-data", default=str(DEFAULT_RACE_DATA))
    parser.add_argument("--beforeinfo", default=str(DEFAULT_BEFOREINFO))
    parser.add_argument("--morning-odds", default=str(DEFAULT_MORNING_ODDS))
    parser.add_argument("--closing-odds", default=str(DEFAULT_CLOSING_ODDS))
    parser.add_argument("--clv-log", default=str(DEFAULT_CLV_LOG))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--endpoint", default=jev_shadow.API_ENDPOINT)
    parser.add_argument("--model", default=jev_shadow.JEV_MODEL)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main() -> int:
    try:
        return run(parse_args())
    except Exception as exc:
        print(f"[ERROR] Jevバックテスト失敗: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
