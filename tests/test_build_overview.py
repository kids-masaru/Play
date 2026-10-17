"""まとめページ集計（運用チェック・結論ボード・心得集の今・公開範囲・障害分離）を確認する。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_overview as bo  # noqa: E402
import playbook as pb  # noqa: E402

TODAY = "2026-10-17"
FIVE_HIT = "1-2-3:100, 1-3-2:100, 1-2-4:100, 1-4-2:100, 2-1-3:100"
FIVE_MISS = "4-5-6:100, 4-6-5:100, 5-4-6:100, 5-6-4:100, 6-5-4:100"


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0].keys()) if rows else ["RaceID"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class OverviewTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data_dir = root / "data"
        self.base_dir = root / "playbooks"
        self.data_dir.mkdir()
        (self.data_dir / "daily_race_info.json").write_text(
            json.dumps({"date": TODAY, "races": [{"race_id": f"R{i}"} for i in range(2)]}), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def predictions(self, key: str, rows: list[tuple[str, str, str]]) -> None:
        config = bo.MODEL_PREDICTION_CONFIGS[key]
        _write_csv(self.data_dir / config["file"], [{"RaceID": r, "Date": d, config["stakes"]: s} for r, d, s in rows])


class OpsTest(OverviewTestBase):
    def test_status_streak_and_alert(self) -> None:
        days = ["2026-10-14", "2026-10-15", "2026-10-16", TODAY]
        # Codex は毎日2レース。Claude は15日から止まっている（3日連続失敗 → 赤）
        self.predictions("codex", [(f"{d}_{i}", d, FIVE_HIT) for d in days for i in range(2)])
        self.predictions("claude", [("x", "2026-10-14", FIVE_HIT)])
        # Gemini は今日1レースだけ（一部欠け）
        self.predictions("gemini", [("g", TODAY, FIVE_HIT), ("g2", TODAY, "")])
        ops = bo.build_ops(self.data_dir, self.base_dir, TODAY)
        by_key = {m["key"]: m for m in ops["models"]}
        self.assertEqual(by_key["codex"]["status"], "ok")
        self.assertFalse(by_key["codex"]["alert"])
        self.assertEqual(by_key["claude"]["status"], "failed")
        self.assertEqual(by_key["claude"]["fail_streak_days"], 3)
        self.assertTrue(by_key["claude"]["alert"])
        self.assertEqual(by_key["claude"]["last_success_date"], "2026-10-14")
        self.assertEqual(by_key["gemini"]["status"], "partial")
        self.assertEqual(by_key["gemini"]["today_count"], 1)
        # 予測CSVが無いモデルも失敗として並ぶ
        self.assertEqual(by_key["grok"]["status"], "failed")

    def test_jobs(self) -> None:
        self.base_dir.mkdir()
        (self.base_dir / "reflect_state.json").write_text(
            json.dumps({"codex": {"target_date": TODAY, "status": "done"}, "claude": {"target_date": "2026-10-16"}}),
            encoding="utf-8",
        )
        (self.data_dir / "jev_shadow_decisions.json").write_text(
            json.dumps({"date": TODAY, "summary": {"decisions": 2, "errors": 0}}), encoding="utf-8"
        )
        jobs = {j["key"]: j for j in bo.build_ops(self.data_dir, self.base_dir, TODAY)["jobs"]}
        self.assertEqual(jobs["reflect"]["status"], "partial")
        self.assertIn("1/5", jobs["reflect"]["detail"])
        self.assertEqual(jobs["playbook_predict"]["status"], "pending")
        self.assertEqual(jobs["jev"]["status"], "ok")


class BoardTest(OverviewTestBase):
    def test_paired_comparison_uses_only_common_settled_races(self) -> None:
        _write_csv(
            self.data_dir / "daily_history_results.csv",
            [
                {"Date": "2026-10-16", "ID": "A", "Result": "1-2-3", "Payout": 1000},
                {"Date": "2026-10-16", "ID": "B", "Result": "1-2-3", "Payout": 1000},
                {"Date": "2026-10-16", "ID": "C", "Result": "1-2-3", "Payout": 1000},
            ],
        )
        self.predictions("codex", [("A", "2026-10-16", FIVE_MISS), ("B", "2026-10-16", FIVE_MISS), ("C", "2026-10-16", "")])
        stream = bo.PLAYBOOK_STREAMS["codex"]
        _write_csv(
            self.data_dir / stream["file"],
            [
                {"RaceID": "A", "Date": "2026-10-16", f"Stakes_{stream['tag']}": FIVE_HIT, "PlaybookUsedIds": "codex-001"},
                {"RaceID": "C", "Date": "2026-10-16", f"Stakes_{stream['tag']}": FIVE_HIT, "PlaybookUsedIds": ""},
                {"RaceID": "D", "Date": "2026-10-17", f"Stakes_{stream['tag']}": FIVE_HIT, "PlaybookUsedIds": ""},
            ],
        )
        row = bo.compare_playbook(self.data_dir, "codex", bo.load_results(self.data_dir))
        # A だけが「両方あり・結果確定」。B は心得集版なし、C は既存版が空、D は結果待ち
        self.assertEqual(row["diff"]["n"], 1)
        self.assertEqual(row["baseline"]["profit_yen"], -500)
        self.assertEqual(row["playbook"]["profit_yen"], 500)
        self.assertEqual(row["diff"]["mean_diff_yen"], 1000)
        self.assertIsNone(row["diff"]["ci95"])  # 30件未満は区間を出さない
        self.assertEqual(row["verdict"], "accruing")

    def test_bootstrap_and_verdict(self) -> None:
        self.assertEqual(bo.verdict(bo.paired_bootstrap([100.0] * 40)), "accruing")  # 500件未満
        better = bo.paired_bootstrap([100.0 + (i % 7) for i in range(500)])
        self.assertGreater(better["ci95"][0], 0)
        self.assertEqual(bo.verdict(better), "playbook_better")
        worse = bo.paired_bootstrap([-100.0 - (i % 5) for i in range(500)])
        self.assertEqual(bo.verdict(worse), "baseline_better")
        mixed = bo.paired_bootstrap([(-1) ** i * 500.0 for i in range(500)])
        self.assertEqual(bo.verdict(mixed), "no_difference")
        # 同じ入力なら毎回同じ区間（固定シード）
        self.assertEqual(bo.paired_bootstrap([float(i) for i in range(50)]), bo.paired_bootstrap([float(i) for i in range(50)]))

    def test_metrics_without_largest_win(self) -> None:
        m = bo.metrics([
            {"invest": 500, "return": 5000, "profit": 4500, "hit": True},
            {"invest": 500, "return": 0, "profit": -500, "hit": False},
            {"invest": 500, "return": 250, "profit": -250, "hit": True},
        ])
        self.assertEqual(m["roi_pct"], round(5250 / 1500 * 100, 1))
        self.assertEqual(m["roi_without_largest_win_pct"], 25.0)
        self.assertEqual(m["hit_rate_pct"], 66.7)


class PlaybookSectionTest(OverviewTestBase):
    def test_only_top3_texts_are_published(self) -> None:
        book = pb.apply_ops(
            pb.empty_playbook("claude"),
            [{"op": "add", "text": f"心得{i}"} for i in range(1, 5)],
            target_date="2026-10-15",
            result_last_date=None,
            reflector="codex",
        )["playbook"]
        book = pb.apply_ops(book, [{"op": "disable", "id": "claude-004", "reason": "不要"}], target_date="2026-10-16", result_last_date=None, reflector="codex")["playbook"]
        pb.save_playbook(book, self.base_dir)
        pb.append_changes(
            [{"date": "2026-10-16", "model_key": "claude", "op": "add", "status": "applied"},
             {"date": "2026-10-01", "model_key": "claude", "op": "add", "status": "applied"},
             {"date": "2026-10-16", "model_key": "claude", "op": "add", "status": "rejected"}],
            self.base_dir,
        )
        _write_csv(
            self.data_dir / "daily_history_results.csv",
            [{"Date": "2026-10-16", "ID": f"R{i}", "Result": "1-2-3", "Payout": 1000} for i in range(4)],
        )
        stream = bo.PLAYBOOK_STREAMS["claude"]
        used = ["claude-001 claude-002 claude-003 claude-004", "claude-001 claude-002", "claude-001", "claude-002 claude-001"]
        _write_csv(
            self.data_dir / stream["file"],
            [{"RaceID": f"R{i}", "Date": "2026-10-16", f"Stakes_{stream['tag']}": FIVE_HIT, "PlaybookUsedIds": u} for i, u in enumerate(used)],
        )
        section = bo.build_playbooks(self.data_dir, self.base_dir, bo.load_results(self.data_dir), TODAY)
        claude = next(m for m in section["models"] if m["key"] == "claude")
        self.assertEqual(claude["active_count"], 3)
        self.assertEqual(claude["week_changes"], {"add": 1, "update": 0, "disable": 0})
        self.assertEqual([i["id"] for i in claude["top_items"]], ["claude-001", "claude-002", "claude-003"])
        self.assertEqual(claude["top_items"][0]["n"], 4)
        dumped = json.dumps(section, ensure_ascii=False)
        self.assertNotIn("心得4", dumped)  # 上位3件以外の本文は出さない


class BuildTest(OverviewTestBase):
    def test_broken_input_does_not_break_other_sections(self) -> None:
        from unittest.mock import patch

        (self.data_dir / "model_performance.json").write_text("{壊れた", encoding="utf-8")
        with patch.object(bo, "build_ops", side_effect=KeyError("races")):
            overview = bo.build(self.data_dir, self.base_dir, TODAY)
        self.assertEqual(overview["ops"], {"status": "unavailable"})
        self.assertIn("ops", overview["errors"][0])
        self.assertIn("models", overview["board"])
        self.assertEqual(overview["backtest"]["status"] in ("not_started", "done"), True)
        self.assertIn("periods", overview["overall"])


if __name__ == "__main__":
    unittest.main()
