"""G：心得集の週1見直し（playbook_weekly_report.py）を確認する。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import playbook as pb  # noqa: E402
import playbook_weekly_report as wr  # noqa: E402

MONDAY = "2026-10-26"


class WeeklyReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data_dir = root / "data"
        self.base_dir = root / "playbooks"
        self.reports_dir = root / "reports"
        self.data_dir.mkdir()
        self.base_dir.mkdir()

        # 10/1 に2件、10/25 に1件追加（10/25 の分だけが「今週の変更」）
        book = pb.empty_playbook("codex")
        first = pb.apply_ops(book, [{"op": "add", "text": "負けが続く心得"}, {"op": "add", "text": "使われない心得"}],
                             target_date="2026-10-01", result_last_date=None, reflector="claude")
        second = pb.apply_ops(first["playbook"], [{"op": "add", "text": "今週の心得"}],
                              target_date="2026-10-25", result_last_date="2026-10-24", reflector="claude")
        pb.save_playbook(second["playbook"], self.base_dir)
        pb.append_changes(first["applied"] + second["applied"], self.base_dir)

        # codex-001 を使った10レース。どれも外れ（心得集あり・なしとも −100円）
        races = [(f"r{i}", f"2026-10-{20 + i % 6:02d}") for i in range(10)]
        (self.data_dir / "daily_history_results.csv").write_text(
            "ID,Date,Result,Payout\n" + "".join(f"{r},{d},6-5-4,1000\n" for r, d in races), encoding="utf-8")
        (self.data_dir / "daily_codex_playbook_predictions.csv").write_text(
            "RaceID,Date,Stakes_CodexPB,PlaybookUsedIds\n" + "".join(f"{r},{d},1-2-3:100,codex-001\n" for r, d in races),
            encoding="utf-8")
        (self.data_dir / "daily_codex_predictions.csv").write_text(
            "RaceID,Date,Stakes_Codex\n" + "".join(f"{r},{d},1-2-3:100\n" for r, d in races), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _args(self, *extra: str):
        return wr.parse_args([*extra, "--data-dir", str(self.data_dir), "--base-dir", str(self.base_dir),
                              "--reports-dir", str(self.reports_dir)])

    def test_week_window(self) -> None:
        self.assertEqual(wr.week_window(MONDAY), {
            "changes_from": "2026-10-20", "changes_to": "2026-10-26",
            "results_from": "2026-10-19", "results_to": "2026-10-25",
        })

    def test_report_counts_changes_usage_and_flags(self) -> None:
        report = wr.build_report(MONDAY, self.data_dir, self.base_dir)
        codex = next(m for m in report["models"] if m["key"] == "codex")
        self.assertEqual(codex["active_count"], 3)
        self.assertEqual([c["item_id"] for c in codex["applied"]], ["codex-003"])
        items = {i["id"]: i for i in codex["items"]}
        self.assertEqual(items["codex-001"]["usage"]["total"]["n"], 10)
        self.assertEqual(items["codex-001"]["usage"]["total"]["profit_yen"], -1000)
        self.assertEqual(items["codex-001"]["flag"], "損が続いている")
        self.assertEqual(items["codex-002"]["flag"], "25日間使われていない")
        self.assertIsNone(items["codex-003"]["flag"])  # 作ったばかりは候補にしない
        self.assertEqual(codex["total_effect"]["n"], 10)
        self.assertEqual(codex["total_effect"]["mean_diff_yen"], 0.0)

        markdown = wr.render_markdown(report)
        self.assertIn("負けが続く心得", markdown)
        self.assertIn("⚠ 損が続いている", markdown)
        line = wr.render_line(report, self.reports_dir / "x.md")
        self.assertIn("⚠codex-001", line)
        self.assertLessEqual(len(line), wr.LINE_MAX_CHARS)

    def test_models_without_used_ids_are_not_flagged_as_unused(self) -> None:
        old_item = {"id": "gemma_ft-001", "status": pb.STATUS_ACTIVE, "created_at": "2026-10-01"}
        self.assertIsNone(wr.review_flag(old_item, None, MONDAY, tracks_usage=False))
        self.assertEqual(wr.review_flag(old_item, None, MONDAY), "25日間使われていない")

    def test_only_monday_and_only_once(self) -> None:
        self.assertEqual(wr.run(self._args("--date", "2026-10-27"))["status"], "skipped_not_monday")
        with patch.object(wr, "send_line", return_value=True) as send:
            self.assertEqual(wr.run(self._args("--date", MONDAY))["status"], "sent")
            self.assertEqual(wr.run(self._args("--date", MONDAY))["status"], "skipped_already_sent")
        self.assertEqual(send.call_count, 1)
        self.assertTrue((self.reports_dir / f"playbook_weekly_{MONDAY}.md").is_file())

    def test_no_line_writes_report_without_marking_sent(self) -> None:
        with patch.object(wr, "send_line") as send:
            self.assertEqual(wr.run(self._args("--date", MONDAY, "--no-line"))["status"], "written")
        send.assert_not_called()
        self.assertEqual(wr.load_state(self.base_dir), {})

    def test_manual_disable_is_recorded_and_applies_from_tomorrow(self) -> None:
        done = wr.disable_item("codex-002", "使われないため", today=MONDAY, base_dir=self.base_dir)
        self.assertEqual(done["effective_from"], "2026-10-27")
        book = pb.load_playbook("codex", self.base_dir)
        self.assertEqual({i["id"]: i["status"] for i in book["items"]}["codex-002"], pb.STATUS_DISABLED)
        snapshot = pb.load_snapshot("codex", "2026-10-27", self.base_dir)
        self.assertNotIn("codex-002", [i["id"] for i in pb.active_items(snapshot["playbook"])])
        changes = wr.load_changes(self.base_dir, "2026-10-27", "2026-10-27")["codex"]
        self.assertEqual(changes[-1]["reflector"], "manual")
        with self.assertRaises(pb.PlaybookError):
            wr.disable_item("codex-002", "もう一度", today=MONDAY, base_dir=self.base_dir)
        with self.assertRaises(pb.PlaybookError):
            wr.disable_item("unknown-001", "理由", today=MONDAY, base_dir=self.base_dir)

    def test_disable_requires_reason(self) -> None:
        with self.assertRaises(SystemExit):
            wr.parse_args(["--disable", "codex-001"])


class WiringTest(unittest.TestCase):
    def test_runs_first_in_morning_batch_and_report_is_private(self) -> None:
        bat = (ROOT / "run_morning.bat").read_text(encoding="utf-8")
        self.assertLess(bat.index("python playbook_weekly_report.py"), bat.index("python morning_odds_runner.py"))
        self.assertIn("reports/playbook_weekly_*.md", (ROOT / ".gitignore").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
