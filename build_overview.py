"""まとめページ用の集計 overview.json を作る。

1画面で「運用が正しく動いているか」「どの方式が効いているか」「心得集がどう育っているか」を
見られるようにする（10/6〜10/15 の Claude 停止に9日間気づけなかった反省から）。

- 読むだけ：既存の予測CSV・結果CSV・Jev/モデル比較の集計JSON・心得集（非公開）。
- 書くのは dashboard/public/daily_data/overview.json だけ。既存のJSONは変えない。
- 心得集から公開するのは件数・変更数・成績と、よく使われた心得の上位3件の本文だけ
  （Masaru確認済み 2026-10-15）。心得集ファイル本体・変更履歴・振り返りの生出力は出さない。
- 各セクションは独立に集計し、1つが失敗しても他のセクションと画面は壊さない。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import playbook as pb
from paired_stats import DECISION_SAMPLE, paired_bootstrap, robustness_metrics, verdict
from codex_learning import MODEL_PREDICTION_CONFIGS, normalize_result, parse_stakes, safe_float
from playbook_predict import STREAMS as PLAYBOOK_STREAMS


for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "dashboard" / "public" / "daily_data"
OUTPUT_JSON = DATA_DIR / "overview.json"
SCHEMA_VERSION = "overview_v2"

# 運用チェックの対象（モデル比較に出ている7モデル。基本Gemmaは対象外の既存方針どおり）
OPS_MODELS = ("codex", "claude", "gemini", "grok", "gemma_ft", "qwen_claude", "qwen_grok_x")
SHORT_LABELS = {
    "codex": "Codex",
    "claude": "Claude",
    "gemini": "Gemini",
    "grok": "Grok",
    "gemma_ft": "学習Gemma（Gemini先生）",
    "qwen_claude": "学習Qwen（Claude先生）",
    "qwen_grok_x": "学習Qwen（Grok+X先生）",
}
ALERT_STREAK_DAYS = 2  # 2日以上続けて失敗したら赤で目立たせる
TOP_PLAYBOOK_ITEMS = 3


# ---------------------------------------------------------------------------
# 共通：読み込み
# ---------------------------------------------------------------------------


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_results(data_dir: Path) -> dict[str, dict[str, Any]]:
    """確定結果：RaceID → {date, result, payout}（払戻は100円あたり）。"""
    results: dict[str, dict[str, Any]] = {}
    for row in read_csv_rows(Path(data_dir) / "daily_history_results.csv"):
        race_id = str(row.get("ID", "")).strip()
        result = normalize_result(row.get("Result"))
        if race_id and result:
            results[race_id] = {
                "date": str(row.get("Date", "")),
                "result": result,
                "payout": safe_float(row.get("Payout"), 0) or 0,
            }
    return results


def prediction_rows(data_dir: Path, file_name: str, stakes_field: str) -> dict[str, dict[str, Any]]:
    """予測CSV：RaceID → {date, picks, used_ids}。買い目が空の行も date だけは残す。"""
    rows: dict[str, dict[str, Any]] = {}
    for row in read_csv_rows(Path(data_dir) / file_name):
        race_id = str(row.get("RaceID", "")).strip()
        if not race_id:
            continue
        rows[race_id] = {
            "date": str(row.get("Date", "")),
            "picks": parse_stakes(row.get(stakes_field)),
            "used_ids": str(row.get("PlaybookUsedIds", "") or "").split(),
        }
    return rows


def settle(prediction: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """1レース分の投資・払戻・損益を計算する。"""
    invest = sum(stake for _, stake in prediction["picks"])
    hit_stake = sum(stake for combo, stake in prediction["picks"] if combo == result["result"])
    returned = hit_stake * result["payout"] / 100
    return {"invest": invest, "return": returned, "profit": returned - invest, "hit": hit_stake > 0}


def metrics(settled: list[dict[str, Any]]) -> dict[str, Any]:
    """共通定義による実収支・高配当依存・損失耐性を返す。"""

    shared = robustness_metrics(settled)
    return {"n": shared["graded_races"], **shared}


# paired_bootstrap・verdict は paired_stats.py に共通化（Jev 組合せ成績と同じ判定にする）


# ---------------------------------------------------------------------------
# 1. 今日の運用チェック
# ---------------------------------------------------------------------------


def build_ops(data_dir: Path, base_dir: Path, today: str) -> dict[str, Any]:
    race_info = read_json(Path(data_dir) / "daily_race_info.json") or {}
    target_date = str(race_info.get("date", "") or today)
    target_races = len(race_info.get("races") or [])

    counts: dict[str, dict[str, int]] = {}
    for key in OPS_MODELS:
        config = MODEL_PREDICTION_CONFIGS[key]
        by_date: dict[str, int] = defaultdict(int)
        for row in prediction_rows(data_dir, config["file"], config["stakes"]).values():
            if row["picks"]:
                by_date[row["date"]] += 1
        counts[key] = dict(by_date)

    # 「バッチが動いた日」= どれかのモデルが予測した日。連続失敗はこの日付で数える。
    batch_days = sorted({day for per in counts.values() for day in per if day and day <= target_date})
    if target_date not in batch_days:
        batch_days.append(target_date)

    models = []
    for key in OPS_MODELS:
        per = counts[key]
        today_count = per.get(target_date, 0)
        succeeded = [day for day, count in per.items() if count > 0 and day <= target_date]
        streak = 0
        for day in reversed(batch_days):
            if per.get(day, 0) > 0:
                break
            streak += 1
        if target_races and today_count >= target_races:
            status = "ok"
        elif today_count > 0:
            status = "partial"
        else:
            status = "failed"
        models.append({
            "key": key,
            "label": SHORT_LABELS[key],
            "today_count": today_count,
            "target_races": target_races,
            "last_success_date": max(succeeded) if succeeded else None,
            "fail_streak_days": streak,
            "status": status,
            "alert": streak >= ALERT_STREAK_DAYS,
        })

    return {
        "date": target_date,
        "target_races": target_races,
        "models": models,
        "jobs": build_jobs(data_dir, base_dir, target_date, target_races),
    }


def build_jobs(data_dir: Path, base_dir: Path, target_date: str, target_races: int) -> list[dict[str, Any]]:
    """振り返り・心得集あり版予測・Jev の状態を1行ずつ。"""
    jobs: list[dict[str, Any]] = []

    # 振り返り：前夜に「今日用」の心得集を作れていれば正常
    state = read_json(Path(base_dir) / "reflect_state.json") or {}
    done = [k for k in pb.MODEL_KEYS if (state.get(k) or {}).get("target_date", "") >= target_date]
    jobs.append({
        "key": "reflect",
        "label": "振り返り（心得集の更新）",
        "detail": f"{len(done)}/{len(pb.MODEL_KEYS)}モデルが今日用に更新済み",
        "status": "ok" if len(done) == len(pb.MODEL_KEYS) else ("partial" if done else "failed"),
        "note": "前夜23時のバッチで実行",
    })

    # 心得集あり版の予測：朝バッチの最後に動くので、公開時点では「この後実行」のことがある
    saved_today = 0
    models_today = 0
    latest = None
    for key, stream in PLAYBOOK_STREAMS.items():
        rows = prediction_rows(data_dir, stream["file"], f"Stakes_{stream['tag']}")
        dates = [row["date"] for row in rows.values() if row["picks"]]
        count = sum(1 for row in rows.values() if row["picks"] and row["date"] == target_date)
        if count:
            models_today += 1
            saved_today += count
        if dates:
            latest = max(latest or "", max(dates))
    jobs.append({
        "key": "playbook_predict",
        "label": "心得集あり版の予測",
        "detail": f"今日 {models_today}モデル・{saved_today}件" if models_today else f"最終 {latest or 'まだありません'}",
        "status": "ok" if models_today else "pending",
        "note": "朝バッチの最後に実行（この画面の公開より後のことがある）",
    })

    # Jev：今日の判定がエラーなく揃っているか
    jev = read_json(Path(data_dir) / "jev_shadow_decisions.json") or {}
    summary = jev.get("summary") or {}
    if jev.get("date") != target_date:
        status, detail = "failed", f"最終 {jev.get('date') or 'まだありません'}"
    elif summary.get("errors"):
        status, detail = "partial", f"{summary.get('decisions', 0)}件・エラー{summary.get('errors')}件"
    else:
        status, detail = "ok", f"{summary.get('decisions', 0)}/{target_races}レース判定"
    jobs.append({"key": "jev", "label": "Jev判定（シャドー）", "detail": detail, "status": status, "note": "実購入には未接続"})
    return jobs


# ---------------------------------------------------------------------------
# 2. 実験の結論ボード
# ---------------------------------------------------------------------------


def compare_playbook(data_dir: Path, model_key: str, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """同じレースで「なし（既存）」と「あり（心得集）」を比べる。"""
    config = MODEL_PREDICTION_CONFIGS[model_key]
    stream = PLAYBOOK_STREAMS[model_key]
    baseline = prediction_rows(data_dir, config["file"], config["stakes"])
    playbook_rows = prediction_rows(data_dir, stream["file"], f"Stakes_{stream['tag']}")
    pairs_base, pairs_pb, diffs = [], [], []
    for race_id, pb_row in playbook_rows.items():
        base_row = baseline.get(race_id)
        result = results.get(race_id)
        if not result or not pb_row["picks"] or not base_row or not base_row["picks"]:
            continue
        a, b = settle(base_row, result), settle(pb_row, result)
        pairs_base.append(a)
        pairs_pb.append(b)
        diffs.append(b["profit"] - a["profit"])
    diff = paired_bootstrap(diffs)
    return {
        "baseline": metrics(pairs_base),
        "playbook": metrics(pairs_pb),
        "diff": diff,
        "verdict": verdict(diff),
        "progress_pct": round(min(len(diffs) / DECISION_SAMPLE, 1) * 100, 1),
        "first_date": min((playbook_rows[r]["date"] for r in playbook_rows if playbook_rows[r]["picks"]), default=None),
    }


def jev_cell(arms: dict[str, Any], arm_id: str) -> dict[str, Any] | None:
    metric = ((arms.get(arm_id) or {}).get("forced_selected")) or None
    if not metric:
        return None
    return {
        "n": metric.get("purchased_races", 0),
        "graded_races": metric.get("graded_races", 0),
        "hits": metric.get("hits", 0),
        "profit_yen": metric.get("profit_yen", 0),
        "roi_pct": metric.get("roi_pct"),
        "hit_rate_pct": metric.get("hit_rate_pct"),
        "roi_without_largest_win_pct": metric.get("roi_without_largest_win_pct"),
    }


def build_board(data_dir: Path, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    jev = read_json(Path(data_dir) / "jev_pairing_performance.json") or {}
    arms = jev.get("arms") or {}
    rows = []
    for key in pb.MODEL_KEYS:
        comparison = compare_playbook(data_dir, key, results)
        row: dict[str, Any] = {
            "key": key,
            "label": SHORT_LABELS[key],
            "kind": "strong" if key in ("codex", "claude") else "local",
            **comparison,
        }
        if row["kind"] == "strong":
            row["jev"] = jev_cell(arms, f"{key}_jev")
            row["jev_note"] = f"Jev実験の期間（確定 {jev.get('latest_result_date') or '—'} まで）。心得集とは対象レースが違う参考値"
            row["playbook_jev"] = jev_cell(arms, f"{key}_playbook_jev")
            # 同じレースでの「Jev」と「心得集＋Jev」の比較（jev_pairing_performance.py が集計）
            row["jev_effect"] = ((jev.get("playbook_effect") or {}).get(key) or {}).get("jev")
        rows.append(row)
    return {"decision_sample": DECISION_SAMPLE, "models": rows}


# ---------------------------------------------------------------------------
# 3. 心得集の今
# ---------------------------------------------------------------------------


def build_playbooks(data_dir: Path, base_dir: Path, results: dict[str, dict[str, Any]], today: str) -> dict[str, Any]:
    week_start = (datetime.strptime(today, "%Y-%m-%d").date() - timedelta(days=6)).isoformat()
    changes: dict[str, dict[str, int]] = defaultdict(lambda: {"add": 0, "update": 0, "disable": 0})
    changes_path = Path(base_dir) / pb.CHANGES_FILE_NAME
    if changes_path.is_file():
        for line in changes_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("status") == "applied" and str(row.get("date", "")) >= week_start and row.get("op") in ("add", "update", "disable"):
                changes[row.get("model_key")][row["op"]] += 1

    models = []
    for key in pb.MODEL_KEYS:
        try:
            book = pb.load_playbook(key, base_dir)
        except pb.PlaybookError:
            models.append({"key": key, "label": SHORT_LABELS[key], "status": "broken"})
            continue
        items = {item["id"]: item for item in book["items"]}
        stream = PLAYBOOK_STREAMS[key]
        usage: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for race_id, row in prediction_rows(data_dir, stream["file"], f"Stakes_{stream['tag']}").items():
            result = results.get(race_id)
            if not result or not row["picks"]:
                continue
            outcome = settle(row, result)
            for item_id in row["used_ids"]:
                if item_id in items:
                    usage[item_id].append(outcome)
        top = sorted(usage.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:TOP_PLAYBOOK_ITEMS]
        models.append({
            "key": key,
            "label": SHORT_LABELS[key],
            "reflector": pb.REFLECTOR_ASSIGNMENT[key],
            "status": "ok",
            "active_count": len(pb.active_items(book)),
            "updated_for": book.get("updated_for"),
            "week_changes": dict(changes.get(key) or {"add": 0, "update": 0, "disable": 0}),
            # Masaru確認済み（10/15）：上位3件だけ本文を公開する
            "top_items": [
                {
                    "id": item_id,
                    "text": items[item_id]["text"],
                    "status": items[item_id]["status"],
                    **{k: metrics(rows)[k] for k in ("n", "hits", "profit_yen", "roi_pct")},
                }
                for item_id, rows in top
            ],
        })
    return {"week_start": week_start, "models": models}


# ---------------------------------------------------------------------------
# 4. 過去30日検証 / 5. 全体成績
# ---------------------------------------------------------------------------


def build_backtest() -> dict[str, Any]:
    summary = read_json(ROOT / "reports" / "playbook_backtest_summary.json")
    if not summary:
        return {"status": "not_started", "note": "過去30日（9/15〜10/14）の検証はまだ実施していません。"}
    return {"status": "done", **summary}


def build_overall(data_dir: Path) -> dict[str, Any]:
    perf = read_json(Path(data_dir) / "model_performance.json") or {}
    periods = perf.get("periods") or {}
    result: dict[str, Any] = {"latest_result_date": perf.get("latest_result_date"), "periods": {}}
    for period_key in ("weekly", "monthly"):
        period = periods.get(period_key) or {}
        view = period.get("dashboard") or period
        combined = view.get("combined") or {}
        measured = [m for m in (view.get("models") or []) if m.get("n")]
        top = max(measured, key=lambda m: m.get("profit", 0), default=None)
        combined_view = {
            key: combined.get(key)
            for key in (
                "n", "hits", "invest", "return", "profit", "roi", "hit_rate",
                "max_drawdown", "longest_losing_streak",
                "roi_without_largest_win", "roi_without_top3_wins",
                "largest_return_share", "top3_return_share",
            )
        }
        combined_view["assessment"] = assess_overall(combined_view)
        result["periods"][period_key] = {
            "label": period.get("label"),
            "start_date": period.get("start_date"),
            "end_date": period.get("end_date"),
            "combined": combined_view,
            "top_model": {k: top.get(k) for k in ("label", "profit", "roi", "n")} if top else None,
            "positive_models": sum(1 for m in measured if m.get("profit", 0) > 0),
            "measured_models": len(measured),
        }
    result["decision_sample"] = DECISION_SAMPLE
    return result


def assess_overall(metric: dict[str, Any]) -> dict[str, Any]:
    """実収支とストレス結果を分け、総合ページ用の平易な結論を返す。"""

    n = int(metric.get("n") or 0)
    profit = float(metric.get("profit") or 0)
    without_largest = metric.get("roi_without_largest_win")
    without_top3 = metric.get("roi_without_top3_wins")
    largest_share = metric.get("largest_return_share")
    enough = n >= DECISION_SAMPLE
    concentrated = profit > 0 and (
        (without_largest is not None and without_largest < 100)
        or (largest_share is not None and largest_share >= 50)
    )

    if n == 0:
        code, label, note = "unmeasured", "計測前", "確定結果が入ると評価を始めます。"
    elif profit > 0 and concentrated:
        code, label = "profitable_concentrated", "黒字・高配当依存"
        note = "実際の収支は黒字ですが、利益が少数の高配当に強く支えられています。"
    elif profit > 0 and enough and without_top3 is not None and without_top3 >= 100:
        code, label = "profitable_robust", "黒字・再現性あり"
        note = "実収支が黒字で、上位3件を除くストレス後もROI 100%以上です。"
    elif profit > 0:
        code, label = "profitable_reviewing", "黒字・再現性を確認中"
        note = "実収支は黒字です。件数と高配当を除いた成績を引き続き確認します。"
    elif profit == 0:
        code, label, note = "break_even", "損益分岐・優位未確認", "実収支は損益分岐で、優位性はまだ確認できません。"
    else:
        code, label = "loss_unconfirmed", "赤字・優位未確認"
        note = "現時点の実収支は赤字です。高配当の有無にかかわらず優位性は未確認です。"

    return {
        "code": code,
        "label": label,
        "note": note,
        "sample_code": "enough" if enough else "accruing",
        "sample_label": "判定目安到達" if enough else "蓄積中",
        "sample_progress_pct": round(min(n / DECISION_SAMPLE, 1) * 100, 1),
    }


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------


def _section(name: str, builder: Callable[[], Any], errors: list[str]) -> Any:
    try:
        return builder()
    except Exception as exc:  # noqa: BLE001 - 1セクションの失敗で全体を止めない
        errors.append(f"{name}: {type(exc).__name__}: {exc}")
        return {"status": "unavailable"}


def build(data_dir: Path = DATA_DIR, base_dir: Path = pb.PLAYBOOK_DIR, today: str | None = None) -> dict[str, Any]:
    today = today or date.today().isoformat()
    errors: list[str] = []
    results = _section("results", lambda: load_results(data_dir), errors)
    if not isinstance(results, dict) or results.get("status") == "unavailable":
        results = {}
    return {
        "schema": SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today,
        "latest_result_date": max((r["date"] for r in results.values()), default=None),
        "ops": _section("ops", lambda: build_ops(data_dir, base_dir, today), errors),
        "board": _section("board", lambda: build_board(data_dir, results), errors),
        "playbooks": _section("playbooks", lambda: build_playbooks(data_dir, base_dir, results, today), errors),
        "backtest": _section("backtest", build_backtest, errors),
        "overall": _section("overall", lambda: build_overall(data_dir), errors),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="まとめページ用の overview.json を作ります。")
    parser.add_argument("--out", default=str(OUTPUT_JSON))
    args = parser.parse_args(argv)
    overview = build()
    out = Path(args.out)
    pb._atomic_write_json(out, overview)
    print(f"出力: {out}")
    for error in overview["errors"]:
        print(f"[WARN] 集計できなかった項目: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
