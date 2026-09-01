"""toto予測モデルごとの確定済み自己フィードバックを生成する。"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any


STRATEGY_VERSION = "feedback_v2_model_isolated"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def match_key(match: dict[str, Any]) -> str:
    """同じ試合をtoto・mini toto間で共通に識別する。"""
    return "|".join(
        str(match.get(field) or "").strip() for field in ("date", "home", "away")
    )


def load_model_feedback(
    data_dir: Path,
    target_round: int,
    model_key: str,
) -> dict[str, Any]:
    """対象回より前に確定した、指定モデル自身の予測だけを集計する。"""
    if not model_key or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in model_key):
        raise ValueError(f"不正なモデルキーです: {model_key}")

    evaluated: list[dict[str, Any]] = []
    pattern = str(data_dir / f"{model_key}_round_*.json")
    for raw_path in glob.glob(pattern):
        try:
            prediction_data = load_json(Path(raw_path))
            round_no = int(prediction_data.get("round", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if round_no >= target_round:
            continue

        settled_path = data_dir / f"settled_{round_no}.json"
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
        for prediction in prediction_data.get("predictions", []):
            predicted = str(prediction.get("pick", ""))
            actual = actual_by_key.get(match_key(prediction), "")
            if predicted in {"H", "D", "A"} and actual:
                evaluated.append(
                    {
                        "round": round_no,
                        "home": str(prediction.get("home", "")),
                        "away": str(prediction.get("away", "")),
                        "predicted": predicted,
                        "actual": actual,
                    }
                )

    evaluated.sort(key=lambda row: (row["round"], row["home"], row["away"]))
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
        "model_key": model_key,
        "strategy_version": STRATEGY_VERSION,
        "leakage_guard": f"Only settled rounds before {target_round} were used.",
        "settled_predictions": len(evaluated),
        "hits": hits,
        "hit_rate": round(hits / len(evaluated), 4) if evaluated else None,
        "by_predicted_pick": by_pick,
        "recent_misses": recent_misses,
    }
