"""ボートレース各モデルの共通成績集計。

画面とLINE通知で同じ数字を使うため、予測サマリと確定結果から
7日・30日・全期間の比較JSONを生成する。Detは評価対象から除外する。
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DATA_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")
RESULTS_CSV = os.path.join(PUBLIC_DATA_DIR, "daily_history_results.csv")
PREDICTIONS_JSON = os.path.join(PUBLIC_DATA_DIR, "ai_predictions_summary.json")
OUTPUT_JSON = os.path.join(PUBLIC_DATA_DIR, "model_performance.json")
DASHBOARD_URL = "https://kids-masaru.github.io/Play/"

# 「通常」は実体が分からないため、使用モデル名が伝わる表示へ変更する。
MODELS = [
    {"key": "stakes", "label": "基本Gemma", "short": "基本Gemma", "color": "#4f46e5"},
    {"key": "stakes_gemini", "label": "Gemini", "short": "Gemini", "color": "#059669"},
    {"key": "stakes_grok", "label": "Grok", "short": "Grok", "color": "#7c3aed"},
    {"key": "stakes_gemmaft", "label": "学習Gemma（Gemini先生）", "short": "学Gemini", "color": "#db2777"},
    {"key": "stakes_gemmaclaude", "label": "学習Gemma（Claude先生）", "short": "学Claude", "color": "#0891b2"},
    {"key": "stakes_gemmagrokx", "label": "学習Gemma（Grok+X先生）", "short": "学Grok+X", "color": "#ea580c"},
    {"key": "stakes_codex", "label": "Codex", "short": "Codex", "color": "#0d9488"},
]
MODEL_BY_KEY = {model["key"]: model for model in MODELS}
PERIODS = {
    "weekly": {"label": "直近7日", "days": 7},
    "monthly": {"label": "直近30日", "days": 30},
    "total": {"label": "全期間", "days": None},
}


def _normalize_combo(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return "-".join(digits[:3]) if len(digits) >= 3 else ""


def parse_stakes(value: Any) -> list[dict[str, float]]:
    """JSON形式と ``1-2-3:100`` 形式の両方を安全に読み取る。"""
    if value is None:
        return []
    text = str(value).strip()
    if not text or text.lower() == "nan" or text == "{}":
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return [
                {"combo": combo, "stake": float(stake)}
                for raw_combo, raw_stake in parsed.items()
                if (combo := _normalize_combo(raw_combo))
                and (stake := _safe_number(raw_stake)) > 0
            ]
    except (json.JSONDecodeError, TypeError):
        pass

    picks = []
    for match in re.finditer(r"([1-6])\s*-?\s*([1-6])\s*-?\s*([1-6])\s*[:=]\s*(\d+(?:\.\d+)?)", text):
        stake = _safe_number(match.group(4))
        if stake > 0:
            picks.append({"combo": "-".join(match.group(1, 2, 3)), "stake": stake})
    return picks


def _safe_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_records(
    results_path: str = RESULTS_CSV,
    predictions_path: str = PREDICTIONS_JSON,
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """モデル別の確定済み購入記録と、確定結果の最終日を返す。"""
    with open(predictions_path, "r", encoding="utf-8") as handle:
        predictions = json.load(handle)

    # 再実行による重複結果は、CSVの後ろにある最新行を採用する。
    results_by_id: dict[str, dict[str, str]] = {}
    with open(results_path, "r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            race_id = str(row.get("ID") or row.get("RaceID") or "").strip()
            if race_id and _normalize_combo(row.get("Result")):
                results_by_id[race_id] = row

    records = {model["key"]: [] for model in MODELS}
    latest_date = ""
    for race_id, result_row in results_by_id.items():
        date = str(result_row.get("Date") or "").strip()
        result = _normalize_combo(result_row.get("Result"))
        payout = _safe_number(result_row.get("Payout"))
        if not date or not result:
            continue
        latest_date = max(latest_date, date)
        prediction = predictions.get(race_id) or {}
        for model in MODELS:
            picks = parse_stakes(prediction.get(model["key"]))
            if not picks:
                continue
            invest = sum(pick["stake"] for pick in picks)
            returned = sum(
                pick["stake"] * payout / 100
                for pick in picks
                if pick["combo"] == result
            )
            records[model["key"]].append({
                "id": race_id,
                "date": date,
                "venue": str(result_row.get("Venue") or ""),
                "race": str(result_row.get("R") or ""),
                "invest": invest,
                "return": returned,
                "profit": returned - invest,
                "hit": returned > 0,
            })

    for model_records in records.values():
        model_records.sort(key=lambda row: (row["date"], row["id"]))
    return records, latest_date


def _date_range(latest_date: str, days: int | None, previous: bool = False) -> tuple[str | None, str | None]:
    if not latest_date or days is None:
        return None, latest_date or None
    end = dt.date.fromisoformat(latest_date)
    if previous:
        end -= dt.timedelta(days=days)
    start = end - dt.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def _filter_dates(records: list[dict[str, Any]], start: str | None, end: str | None) -> list[dict[str, Any]]:
    return [row for row in records if (not start or row["date"] >= start) and (not end or row["date"] <= end)]


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    invest = sum(row["invest"] for row in records)
    returned = sum(row["return"] for row in records)
    hits = sum(1 for row in records if row["hit"])
    equity = peak = max_drawdown = 0.0
    for row in sorted(records, key=lambda item: (item["date"], item["id"], item.get("source", ""))):
        equity += row["profit"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "n": len(records),
        "hits": hits,
        "hit_rate": round(hits / len(records) * 100, 1) if records else None,
        "invest": round(invest),
        "return": round(returned),
        "profit": round(returned - invest),
        "roi": round(returned / invest * 100, 1) if invest else None,
        "max_drawdown": round(max_drawdown),
        "sample_status": "十分" if len(records) >= 100 else "確認中" if len(records) >= 30 else "参考",
    }


def _combined(records_by_model: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    # 同じ買い目でもモデルごとに別口として扱うため、重複排除せず連結する。
    return [
        {**row, "source": model_key, "id": f"{row['id']}::{model_key}"}
        for model_key, rows in records_by_model.items()
        for row in rows
    ]


def _trend(
    current_by_model: dict[str, list[dict[str, Any]]],
    all_by_model: dict[str, list[dict[str, Any]]],
    start: str | None,
    end: str | None,
) -> list[dict[str, Any]]:
    dates = sorted({row["date"] for rows in current_by_model.values() for row in rows})
    cumulative = defaultdict(float)
    output = []
    for date_text in dates:
        row: dict[str, Any] = {"date": date_text, "label": date_text[5:]}
        combined_daily_profit = 0.0
        rolling_combined: list[dict[str, Any]] = []
        rolling_start = (dt.date.fromisoformat(date_text) - dt.timedelta(days=6)).isoformat()
        for model in MODELS:
            key = model["key"]
            daily_profit = sum(item["profit"] for item in current_by_model[key] if item["date"] == date_text)
            cumulative[key] += daily_profit
            row[f"profit_{key}"] = round(cumulative[key])
            combined_daily_profit += daily_profit
            rolling_records = _filter_dates(all_by_model[key], rolling_start, date_text)
            rolling_metrics = _metrics(rolling_records)
            row[f"roi_{key}"] = rolling_metrics["roi"]
            rolling_combined.extend({**item, "source": key, "id": f"{item['id']}::{key}"} for item in rolling_records)
        cumulative["combined"] += combined_daily_profit
        row["profit_combined"] = round(cumulative["combined"])
        row["roi_combined"] = _metrics(rolling_combined)["roi"]
        output.append(row)
    return output


def build_performance_payload() -> dict[str, Any]:
    records_by_model, latest_date = load_records()
    periods: dict[str, Any] = {}
    for period_key, period_config in PERIODS.items():
        days = period_config["days"]
        start, end = _date_range(latest_date, days)
        current_by_model = {
            key: _filter_dates(records, start, end)
            for key, records in records_by_model.items()
        }
        previous_start, previous_end = _date_range(latest_date, days, previous=True)
        model_rows = []
        for model in MODELS:
            key = model["key"]
            current_metrics = _metrics(current_by_model[key])
            previous_metrics = _metrics(_filter_dates(records_by_model[key], previous_start, previous_end)) if days else None
            roi_change = None
            if previous_metrics and current_metrics["roi"] is not None and previous_metrics["roi"] is not None:
                roi_change = round(current_metrics["roi"] - previous_metrics["roi"], 1)
            model_rows.append({
                **model,
                **current_metrics,
                "previous_roi": previous_metrics["roi"] if previous_metrics else None,
                "roi_change": roi_change,
                "direction": "up" if roi_change is not None and roi_change >= 5 else "down" if roi_change is not None and roi_change <= -5 else "flat",
            })
        model_rows.sort(key=lambda item: (item["profit"], item["roi"] or -1), reverse=True)
        for index, model_row in enumerate(model_rows, 1):
            model_row["rank"] = index

        combined_records = _combined(current_by_model)
        combined_metrics = _metrics(combined_records)
        periods[period_key] = {
            "label": period_config["label"],
            "start_date": start,
            "end_date": end,
            "models": model_rows,
            "combined": {
                "key": "combined",
                "label": "全モデル合計",
                "short": "全モデル合計",
                "color": "#111827",
                **combined_metrics,
            },
            "trend": _trend(current_by_model, records_by_model, start, end),
        }

    return {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "latest_result_date": latest_date,
        "models": MODELS,
        "periods": periods,
        "calculation_note": "同じ買い目でもモデルごとに別口として投資・払戻を合算",
    }


def generate_performance_file(output_path: str = OUTPUT_JSON) -> dict[str, Any]:
    payload = build_performance_payload()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return payload


def _yen(value: Any) -> str:
    amount = round(_safe_number(value))
    return f"{'+' if amount >= 0 else '-'}¥{abs(amount):,}"


def format_line_report(payload: dict[str, Any] | None = None, period_key: str = "weekly") -> str:
    """個別買い目・答え合わせを含めない、モデル比較専用LINE文面。"""
    data = payload or build_performance_payload()
    period = data["periods"][period_key]
    combined = period["combined"]
    lines = [
        f"📊 ボートレース モデル比較｜{period['label']}",
        f"集計: {period['start_date'] or '開始日'}〜{period['end_date'] or '-'}",
        "",
        "【全モデル合計】",
        f"収支 {_yen(combined['profit'])}｜ROI {combined['roi'] if combined['roi'] is not None else '-'}%",
        f"的中率 {combined['hit_rate'] if combined['hit_rate'] is not None else '-'}%｜延べ{combined['n']}予測",
        f"最大ドローダウン ¥{combined['max_drawdown']:,}",
        "",
        "【モデル別ランキング（収支順）】",
    ]
    for model in period["models"]:
        change = ""
        if model["roi_change"] is not None:
            change = f"｜前期比 {model['roi_change']:+.1f}pt"
        lines.append(
            f"{model['rank']}. {model['short']} {_yen(model['profit'])}｜"
            f"ROI {model['roi'] if model['roi'] is not None else '-'}%｜"
            f"的中 {model['hit_rate'] if model['hit_rate'] is not None else '-'}%｜{model['n']}R{change}"
        )
    lines.extend([
        "",
        "※重複買い目もモデルごとに別口で計算",
        DASHBOARD_URL,
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    generated = generate_performance_file()
    print(f"出力: {OUTPUT_JSON}")
    print(format_line_report(generated))
