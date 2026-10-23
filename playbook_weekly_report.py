"""心得集の週1見直し（毎週月曜の朝、LINE とレポートで知らせる）。

- 各モデルの今週の変更（追加・修正・無効化）と、心得ごとの使用回数・成績をまとめる。
- 損が続いている心得・使われていない心得には「見直し候補」の印を付ける。
- レポート reports/playbook_weekly_<日付>.md は心得の本文を含むので Git 対象外（.gitignore）。
  LINE には要約だけを送る（送り先は井﨑さん本人）。
- 見直しで不要と判断した心得は、Claude Code へ「心得集見直し」と依頼して
  `python playbook_weekly_report.py --disable <ID> --reason "<理由>"` で無効化する。
  手動の無効化も changes.jsonl に記録し、翌日の予測から外れる。
- 読むだけの集計で、AI は呼ばない。失敗しても朝バッチは止めない（常に終了コード0）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import build_overview as bo
import playbook as pb
from paired_stats import paired_bootstrap, verdict

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "reports"
STATE_FILE_NAME = "weekly_state.json"  # 心得集フォルダ（非公開）に置く送信済みの記録
REPORT_WEEKDAY = 0  # 月曜
REVIEW_MIN_USES = 10  # これ以上使われて累計の損益がマイナスなら見直し候補
UNUSED_DAYS = 14  # 作ってからこれ以上たっても一度も使われていなければ見直し候補
LINE_MAX_CHARS = 4500  # LINE の上限（5000字）より少し短く
VERDICT_JA = {
    "accruing": "蓄積中",
    "playbook_better": "ありが優勢",
    "baseline_better": "なしが優勢",
    "no_difference": "差なし",
}


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------


def week_window(today: str) -> dict[str, str]:
    """変更は「今日用までの7日分」、成績は「昨日までの7日分」の確定結果で見る。"""
    day = datetime.strptime(today, "%Y-%m-%d").date()
    return {
        "changes_from": (day - timedelta(days=6)).isoformat(),
        "changes_to": day.isoformat(),
        "results_from": (day - timedelta(days=7)).isoformat(),
        "results_to": (day - timedelta(days=1)).isoformat(),
    }


def load_changes(base_dir: Path, start: str, end: str) -> dict[str, list[dict[str, Any]]]:
    """changes.jsonl から期間内の記録をモデルごとに返す（反映・拒否の両方）。"""
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    path = Path(base_dir) / pb.CHANGES_FILE_NAME
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if start <= str(row.get("date", "")) <= end:
            rows[str(row.get("model_key"))].append(row)
    return rows


def paired(data_dir: Path, model_key: str, results: dict[str, dict[str, Any]], start: str | None = None, end: str | None = None) -> dict[str, Any]:
    """同じレースで「心得集あり − なし」の損益差（期間を絞れる）。"""
    config = bo.MODEL_PREDICTION_CONFIGS[model_key]
    stream = bo.PLAYBOOK_STREAMS[model_key]
    baseline = bo.prediction_rows(data_dir, config["file"], config["stakes"])
    diffs = []
    for race_id, row in bo.prediction_rows(data_dir, stream["file"], f"Stakes_{stream['tag']}").items():
        result = results.get(race_id)
        base = baseline.get(race_id)
        if not result or not row["picks"] or not base or not base["picks"]:
            continue
        if (start and result["date"] < start) or (end and result["date"] > end):
            continue
        diffs.append(bo.settle(row, result)["profit"] - bo.settle(base, result)["profit"])
    diff = paired_bootstrap(diffs)
    return {**diff, "verdict": verdict(diff)}


def item_usage(data_dir: Path, model_key: str, results: dict[str, dict[str, Any]], start: str, end: str) -> dict[str, dict[str, dict[str, Any]]]:
    """心得ごとの使用成績（今週・累計）。使ったと答えたレースの心得集あり版の損益で数える。"""
    stream = bo.PLAYBOOK_STREAMS[model_key]
    week: dict[str, list] = defaultdict(list)
    total: dict[str, list] = defaultdict(list)
    for race_id, row in bo.prediction_rows(data_dir, stream["file"], f"Stakes_{stream['tag']}").items():
        result = results.get(race_id)
        if not result or not row["picks"]:
            continue
        outcome = bo.settle(row, result)
        for item_id in dict.fromkeys(row["used_ids"]):
            total[item_id].append(outcome)
            if start <= result["date"] <= end:
                week[item_id].append(outcome)
    keys = ("n", "hits", "profit_yen", "roi_pct")
    return {
        item_id: {
            "week": {k: bo.metrics(week.get(item_id, []))[k] for k in keys},
            "total": {k: bo.metrics(rows)[k] for k in keys},
        }
        for item_id, rows in total.items()
    }


def review_flag(item: dict[str, Any], usage: dict[str, Any] | None, today: str, *, tracks_usage: bool = True) -> str | None:
    """有効な心得だけに見直し候補の印を付ける。

    使った心得のIDを答えないモデル（tracks_usage=False）は、使用0回が「使われていない」
    ことを意味しないので、未使用の印は付けない。
    """
    if item.get("status") != pb.STATUS_ACTIVE:
        return None
    total = (usage or {}).get("total") or {}
    if (total.get("n") or 0) >= REVIEW_MIN_USES and (total.get("profit_yen") or 0) < 0:
        return "損が続いている"
    created = str(item.get("created_at") or "")
    if tracks_usage and not total.get("n") and created:
        age = (datetime.strptime(today, "%Y-%m-%d").date() - datetime.strptime(created, "%Y-%m-%d").date()).days
        if age >= UNUSED_DAYS:
            return f"{age}日間使われていない"
    return None


def build_report(today: str, data_dir: Path = bo.DATA_DIR, base_dir: Path = pb.PLAYBOOK_DIR) -> dict[str, Any]:
    window = week_window(today)
    results = bo.load_results(data_dir)
    changes = load_changes(base_dir, window["changes_from"], window["changes_to"])
    models = []
    for key in pb.MODEL_KEYS:
        entry: dict[str, Any] = {"key": key, "label": bo.SHORT_LABELS[key], "reflector": pb.REFLECTOR_ASSIGNMENT[key]}
        try:
            book = pb.load_playbook(key, base_dir)
        except pb.PlaybookError as exc:
            models.append({**entry, "error": f"心得集を読めません: {exc}"})
            continue
        usage = item_usage(data_dir, key, results, window["results_from"], window["results_to"])
        tracks_usage = bool(usage)  # 一度でも使った心得のIDを答えたモデルか
        model_changes = changes.get(key, [])
        items = []
        for item in book["items"]:
            # 有効な心得と、今週無効化された心得だけを載せる（古い無効化は省く）
            recent = str(item.get("updated_at") or "") >= window["changes_from"]
            if item.get("status") != pb.STATUS_ACTIVE and not recent:
                continue
            items.append({
                "id": item["id"],
                "text": item["text"],
                "status": item["status"],
                "created_at": item.get("created_at"),
                "usage": usage.get(item["id"]) or {"week": {"n": 0}, "total": {"n": 0}},
                "flag": review_flag(item, usage.get(item["id"]), today, tracks_usage=tracks_usage),
            })
        models.append({
            **entry,
            "tracks_usage": tracks_usage,
            "active_count": len(pb.active_items(book)),
            "applied": [c for c in model_changes if c.get("status") == "applied"],
            "rejected_count": sum(1 for c in model_changes if c.get("status") == "rejected"),
            "week_effect": paired(data_dir, key, results, window["results_from"], window["results_to"]),
            "total_effect": paired(data_dir, key, results),
            "items": items,
        })
    return {"date": today, "window": window, "models": models}


# ---------------------------------------------------------------------------
# 出力（レポート・LINE）
# ---------------------------------------------------------------------------


def _yen(value: Any) -> str:
    if value is None:
        return "—"
    return f"{'+' if value > 0 else ''}{round(value):,}円"


def _effect_line(effect: dict[str, Any]) -> str:
    if not effect.get("n"):
        return "比べられるレースなし"
    text = f"{effect['n']}レース・1レースあたり {_yen(effect['mean_diff_yen'])}"
    if effect.get("ci95"):
        text += f"（95%区間 {_yen(effect['ci95'][0])}〜{_yen(effect['ci95'][1])}）"
    return f"{text}・{VERDICT_JA.get(effect['verdict'], effect['verdict'])}"


def _change_line(change: dict[str, Any]) -> str:
    who = "手動" if change.get("reflector") == "manual" else f"振り返り役 {change.get('reflector')}"
    if change.get("op") == "add":
        return f"- 追加 `{change.get('item_id')}`（{change.get('date')}・{who}）：{change.get('text')}"
    if change.get("op") == "update":
        return f"- 修正 `{change.get('item_id')}`（{change.get('date')}・{who}）：{change.get('previous_text')} → {change.get('text')}"
    return f"- 無効化 `{change.get('item_id')}`（{change.get('date')}・{who}）：理由 {change.get('reason')}"


def render_markdown(report: dict[str, Any]) -> str:
    window = report["window"]
    lines = [
        f"# 心得集の週1見直し（{report['date']}）",
        "",
        f"- 変更の期間：{window['changes_from']}〜{window['changes_to']} 用の心得集",
        f"- 成績の期間：{window['results_from']}〜{window['results_to']} の確定結果（累計も併記）",
        "- 成績は「その心得を使ったと答えたレース」の心得集あり版の損益。1つの心得だけの効果ではない点に注意。",
        f"- 見直し候補：累計{REVIEW_MIN_USES}回以上使われて損益がマイナス、または作ってから{UNUSED_DAYS}日以上使われていない心得。",
        "- 不要な心得は Claude Code に「心得集見直し：<ID> を無効化（理由）」と頼む。翌日の予測から外れる。",
        "",
    ]
    for model in report["models"]:
        lines.append(f"## {model['label']}（振り返り役：{model['reflector']}）")
        lines.append("")
        if model.get("error"):
            lines += [f"- {model['error']}", ""]
            continue
        lines.append(f"- 有効な心得：{model['active_count']}件")
        lines.append(f"- 今週の「あり−なし」：{_effect_line(model['week_effect'])}")
        lines.append(f"- 累計の「あり−なし」：{_effect_line(model['total_effect'])}")
        lines.append("")
        lines.append(f"### 今週の変更（{len(model['applied'])}件・拒否 {model['rejected_count']}件）")
        lines.append("")
        lines += [_change_line(c) for c in model["applied"]] or ["- なし"]
        lines.append("")
        lines.append("### 心得ごとの成績")
        lines.append("")
        if not model["items"]:
            lines += ["- 心得はまだありません", ""]
            continue
        if not model.get("tracks_usage", True):
            lines += ["- このモデルは使った心得のIDを答えないため、心得ごとの使用回数・成績は出せません（全体の「あり−なし」で判断）。", ""]
        lines.append("| ID | 状態 | 今週 使用/的中/損益 | 累計 使用/的中/損益 | 見直し | 本文 |")
        lines.append("|---|---|---|---|---|---|")
        for item in model["items"]:
            week, total = item["usage"]["week"], item["usage"]["total"]
            status = "有効" if item["status"] == pb.STATUS_ACTIVE else "無効"
            text = str(item["text"]).replace("|", "／").replace("\n", " ")
            lines.append(
                f"| `{item['id']}` | {status} "
                f"| {week.get('n', 0)}/{week.get('hits', 0)}/{_yen(week.get('profit_yen')) if week.get('n') else '—'} "
                f"| {total.get('n', 0)}/{total.get('hits', 0)}/{_yen(total.get('profit_yen')) if total.get('n') else '—'} "
                f"| {('⚠ ' + item['flag']) if item['flag'] else ''} | {text} |"
            )
        lines.append("")
    return "\n".join(lines)


def render_line(report: dict[str, Any], report_path: Path) -> str:
    lines = [f"【心得集の週1見直し】{report['date']}", ""]
    for model in report["models"]:
        if model.get("error"):
            lines.append(f"■{model['label']}：{model['error']}")
            continue
        ops = defaultdict(int)
        for change in model["applied"]:
            ops[change.get("op")] += 1
        total = model["total_effect"]
        effect = f"累計{total['n']}R 1Rあたり{_yen(total['mean_diff_yen'])}（{VERDICT_JA.get(total['verdict'])}）" if total.get("n") else "比較データなし"
        lines.append(f"■{model['label']}：有効{model['active_count']}件／今週 追加{ops['add']}・修正{ops['update']}・無効{ops['disable']}")
        lines.append(f"　あり−なし：{effect}")
        for item in model["items"]:
            if item["flag"]:
                lines.append(f"　⚠{item['id']}（{item['flag']}）{str(item['text'])[:40]}…")
    lines += [
        "",
        f"詳細：{report_path.relative_to(ROOT) if report_path.is_relative_to(ROOT) else report_path}",
        "不要な心得は Claude Code に「心得集見直し」と頼んでください。",
    ]
    message = "\n".join(lines)
    return message if len(message) <= LINE_MAX_CHARS else message[: LINE_MAX_CHARS - 20] + "\n…（続きはレポート）"


def send_line(message: str) -> bool:
    """本人のスマホへ週1見直しを送る。

    まず KOTO 経由（LINE とアプリの両方へ届く）。KOTO の設定が無い・届けられないときだけ、
    main_runner.py と同じ環境変数・ライブラリで LINE へ直接送る（LINE卒業までの予備。2026-10-23）。
    """
    # KOTO部品が読み込めなくても処理は止めず、LINEへ直接送る（code-check 10/23）
    try:
        from koto_notice import send_via_koto
        sent_via_koto = send_via_koto("boatrace_weekly", message)
    except Exception as koto_error:
        print(f"  [WARN] KOTO 経由の送信をとばしました: {type(koto_error).__name__}")
        sent_via_koto = False
    if sent_via_koto:
        return True
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not token or not user_id:
        print("[WARN] LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定のため、LINE通知をスキップしました。")
        return False
    from linebot import LineBotApi
    from linebot.models import TextSendMessage

    LineBotApi(token).push_message(user_id, TextSendMessage(text=message))
    print("[SUCCESS] LINEへ心得集の週1見直しを送信しました。")
    return True


# ---------------------------------------------------------------------------
# 手動の無効化（「心得集見直し」と頼まれたとき）
# ---------------------------------------------------------------------------


def disable_item(item_id: str, reason: str, *, today: str, base_dir: Path = pb.PLAYBOOK_DIR) -> dict[str, Any]:
    """心得を1件無効化し、変更記録に残し、翌日用の版にも反映する。"""
    model_key = next((key for key in pb.MODEL_KEYS if item_id.startswith(f"{key}-")), None)
    if model_key is None:
        raise pb.PlaybookError(f"心得IDからモデルが分かりません: {item_id!r}")
    effective = (datetime.strptime(today, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    book = pb.load_playbook(model_key, base_dir)
    result = pb.apply_ops(
        book,
        [{"op": "disable", "id": item_id, "reason": reason}],
        target_date=effective,
        result_last_date=None,
        reflector="manual",
    )
    pb.append_changes(result["applied"] + result["rejected"], base_dir)
    if result["rejected"]:
        raise pb.PlaybookError(result["rejected"][0]["reject_reason"])
    pb.save_playbook(result["playbook"], base_dir)
    # 夜の振り返りが失敗しても翌日の予測から外れるよう、翌日用の版を先に作っておく
    # （振り返りが動けば、この版は心得集本体から作り直される）
    pb.save_snapshot(result["playbook"], effective, base_dir)
    return {"model_key": model_key, "item_id": item_id, "effective_from": effective}


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------


def load_state(base_dir: Path) -> dict[str, Any]:
    path = Path(base_dir) / STATE_FILE_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def run(args: argparse.Namespace) -> dict[str, Any]:
    today = args.date or date.today().isoformat()
    base_dir = Path(args.base_dir)
    if args.disable:
        done = disable_item(args.disable, args.reason or "", today=today, base_dir=base_dir)
        print(f"無効化しました：{done['item_id']}（{done['effective_from']} の予測から外れます）")
        return {"status": "disabled", **done}

    if not args.force and datetime.strptime(today, "%Y-%m-%d").weekday() != REPORT_WEEKDAY:
        print(f"今日（{today}）は月曜ではないため、心得集の週1見直しは作りません。")
        return {"status": "skipped_not_monday"}
    state = load_state(base_dir)
    if not args.force and state.get("last_sent_for") == today:
        print(f"{today} の週1見直しは送信済みです。")
        return {"status": "skipped_already_sent"}

    report = build_report(today, Path(args.data_dir), base_dir)
    reports_dir = Path(args.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"playbook_weekly_{today}.md"
    report_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"レポート：{report_path}")

    sent = False
    if not args.no_line:
        sent = send_line(render_line(report, report_path))
    if sent:
        pb._atomic_write_json(base_dir / STATE_FILE_NAME, {"last_sent_for": today, "sent_at": datetime.now().isoformat(timespec="seconds")})
    return {"status": "sent" if sent else "written", "report": str(report_path)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="心得集の週1見直し（月曜の朝にLINEとレポート）")
    parser.add_argument("--date", help="レポートの日付（YYYY-MM-DD。省略時は今日）")
    parser.add_argument("--force", action="store_true", help="月曜以外・送信済みでも作る")
    parser.add_argument("--no-line", action="store_true", help="LINEは送らずレポートだけ作る")
    parser.add_argument("--disable", metavar="ID", help="心得を1件無効化する（例: claude-003）")
    parser.add_argument("--reason", help="--disable の理由")
    parser.add_argument("--data-dir", default=str(bo.DATA_DIR))
    parser.add_argument("--base-dir", default=str(pb.PLAYBOOK_DIR))
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    args = parser.parse_args(argv)
    if args.disable and not args.reason:
        parser.error("--disable には --reason（無効化の理由）が必要です")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        run(args)
    except Exception as exc:  # noqa: BLE001 - 朝バッチを止めない
        print(f"[ERROR] 心得集の週1見直しに失敗しました: {type(exc).__name__}: {exc}")
        # 手動の無効化の失敗は、頼んだ人に分かるよう終了コード1で返す
        return 1 if args.disable else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
