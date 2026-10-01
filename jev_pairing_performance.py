"""Jev組合せ実験の確定済み成績を集計する。

ローカル履歴と確定結果だけを結合し、Codex/Claudeの元買い目とJev選択を
同じレース単位で比較する。予測生成や実購入は行わない。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import jev_shadow


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


ROOT = Path(__file__).resolve().parent
DEFAULT_HISTORY = ROOT / "daily_data" / "jev_shadow_history.jsonl"
DEFAULT_RESULTS = ROOT / "dashboard" / "public" / "daily_data" / "daily_history_results.csv"
DEFAULT_OUTPUT = (
    ROOT / "dashboard" / "public" / "daily_data" / "jev_pairing_performance.json"
)


def normalize_combo(value: Any) -> str:
    """3連単を ``1-2-3`` 形式へ正規化する。"""

    digits = [char for char in str(value or "") if char.isdigit()]
    if len(digits) < 3 or len(set(digits[:3])) != 3:
        return ""
    return "-".join(digits[:3])


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    """確定結果CSVを読み、同一IDが複数なら末尾を採用する。"""

    results: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID") or row.get("RaceID") or "").strip()
            result = normalize_combo(row.get("Result"))
            if not race_id or not result:
                continue
            try:
                payout = float(row.get("Payout") or 0)
            except (TypeError, ValueError):
                payout = 0.0
            results[race_id] = {
                "race_id": race_id,
                "date": str(row.get("Date") or "").strip(),
                "result": result,
                "payout": payout,
            }
    return results


def grade_picks(
    picks: list[dict[str, Any]], result: str, payout: float
) -> dict[str, Any]:
    """100円払戻表記に合わせ、買い目群の仮想収支を計算する。"""

    invest = sum(float(pick.get("stake_yen") or 0) for pick in picks)
    returned = sum(
        float(pick.get("stake_yen") or 0) * payout / 100
        for pick in picks
        if normalize_combo(pick.get("combo")) == result
    )
    return {
        "invest": round(invest),
        "return": round(returned),
        "profit": round(returned - invest),
        "hit": returned > 0,
    }


def selected_pick(record: dict[str, Any]) -> list[dict[str, Any]]:
    """保存時点の候補一覧からJev選択または元モデル先頭1点を復元する。"""

    selected = normalize_combo(record.get("selected_candidate"))
    if not selected:
        return []
    if record.get("decision_source") == "raw_model":
        candidates = record.get("raw_picks", [])
        stake_key = "stake_yen"
    else:
        candidates = record.get("candidate_snapshot", [])
        stake_key = "total_proposed_stake_yen"
    if not isinstance(candidates, list):
        return []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if normalize_combo(candidate.get("combo")) == selected:
            stake = float(candidate.get(stake_key) or 0)
            return [{"combo": selected, "stake_yen": stake}] if stake > 0 else []
    return []


def metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """ROIと大当たり依存を同時に確認できる集計を返す。"""

    graded = [row[key] for row in rows]
    invest = sum(row["invest"] for row in graded)
    returned = sum(row["return"] for row in graded)
    purchased = sum(row["invest"] > 0 for row in graded)
    hits = sum(bool(row["hit"]) for row in graded)
    equity = 0
    peak = 0
    max_drawdown = 0
    for row in graded:
        equity += row["profit"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    largest_win = max((row["profit"] for row in graded), default=0)
    largest_win = max(0, largest_win)
    without_largest = returned - largest_win
    return {
        "graded_races": len(graded),
        "purchased_races": purchased,
        "hits": hits,
        "hit_rate_pct": round(hits / purchased * 100, 1) if purchased else None,
        "invest_yen": round(invest),
        "return_yen": round(returned),
        "profit_yen": round(returned - invest),
        "roi_pct": round(returned / invest * 100, 1) if invest else None,
        "max_drawdown_yen": round(max_drawdown),
        "largest_single_race_profit_yen": round(largest_win),
        "profit_without_largest_win_yen": round(without_largest - invest),
        "roi_without_largest_win_pct": round(without_largest / invest * 100, 1)
        if invest
        else None,
    }


def evaluate_record(
    record: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any]:
    """結果は保存済み判断へ後から結合し、比較用の各購入規則を採点する。"""

    forced_picks = selected_pick(record)
    raw_picks = record.get("raw_picks", [])
    if not isinstance(raw_picks, list):
        raw_picks = []
    action = str(record.get("action") or "")
    action_picks = forced_picks if action in {"small", "standard"} else []
    return {
        "race_id": result["race_id"],
        "date": result["date"],
        "forced_selected": grade_picks(
            forced_picks, result["result"], result["payout"]
        ),
        "raw_portfolio": grade_picks(
            raw_picks, result["result"], result["payout"]
        ),
        "action_selected": grade_picks(
            action_picks, result["result"], result["payout"]
        ),
    }


def build_report(
    history_path: Path, results_path: Path
) -> dict[str, Any]:
    """現行実験版の履歴だけを確定結果と結合する。"""

    history = jev_shadow.load_history(history_path)
    results = load_results(results_path)
    grouped: dict[str, list[dict[str, Any]]] = {}
    graded_dates: list[str] = []
    for record in history.values():
        if record.get("experiment_version") != jev_shadow.EXPERIMENT_VERSION:
            continue
        if record.get("strategy_version") != jev_shadow.STRATEGY_VERSION:
            continue
        race_id = str(record.get("race_id") or "")
        result = results.get(race_id)
        arm_id = str(record.get("experiment_id") or "")
        if not result or not arm_id:
            continue
        grouped.setdefault(arm_id, []).append(evaluate_record(record, result))
        if result["date"]:
            graded_dates.append(result["date"])

    arms: dict[str, Any] = {}
    for arm in jev_shadow.PAIRING_ARMS:
        arm_id = str(arm["id"])
        rows = sorted(grouped.get(arm_id, []), key=lambda row: (row["date"], row["race_id"]))
        arm_report: dict[str, Any] = {
            "type": arm["type"],
            "graded_races": len(rows),
            "forced_selected": metrics(rows, "forced_selected"),
        }
        if arm["type"] == "raw_model":
            arm_report["raw_portfolio"] = metrics(rows, "raw_portfolio")
        if arm["type"] == "jev_gate_and_selector":
            arm_report["action_selected"] = metrics(rows, "action_selected")
        arms[arm_id] = arm_report

    return {
        "generated_at": datetime.now(jev_shadow.JST).isoformat(timespec="seconds"),
        "shadow_only": True,
        "experiment_version": jev_shadow.EXPERIMENT_VERSION,
        "strategy_version": jev_shadow.STRATEGY_VERSION,
        "latest_result_date": max(graded_dates) if graded_dates else "",
        "arms": arms,
    }


def write_output(path: Path, payload: dict[str, Any]) -> None:
    """公開用集計を一時ファイルから安全に置換する。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jev組合せ実験の確定成績集計")
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser.parse_args(argv)


def main() -> int:
    try:
        args = parse_args()
        report = build_report(Path(args.history), Path(args.results))
        write_output(Path(args.output), report)
        counts = {
            arm_id: arm["graded_races"] for arm_id, arm in report["arms"].items()
        }
        print(
            "Jev組合せ成績を更新しました: "
            + json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
        )
        return 0
    except Exception as exc:
        print(f"[ERROR] Jev組合せ成績の更新に失敗しました: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
