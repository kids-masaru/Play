"""ボートレースのモデル別フィードバックと時系列ガードを確認する。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from codex_learning import load_history_records, model_feedback


class BoatModelFeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.records = [
            {
                "race_id": "past-race",
                "date": "2026-08-30",
                "venue": "戸田",
                "r": 1,
                "result": "1-2-3",
                "payout": 1000,
            }
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_csv(self, name: str, fields: list[str], rows: list[dict[str, str]]) -> None:
        with (self.data_dir / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_feedback_is_isolated_by_model_and_date(self) -> None:
        self._write_csv(
            "daily_codex_predictions.csv",
            ["RaceID", "Date", "Stakes_Codex", "Strategy_Codex"],
            [
                {"RaceID": "past-race", "Date": "2026-08-30", "Stakes_Codex": "1-2-3:100", "Strategy_Codex": "codex-v1"},
                {"RaceID": "target-race", "Date": "2026-09-01", "Stakes_Codex": "1-2-3:100", "Strategy_Codex": "future"},
            ],
        )
        self._write_csv(
            "daily_claude_predictions.csv",
            ["RaceID", "Date", "Stakes_Claude", "Strategy_Claude"],
            [
                {"RaceID": "past-race", "Date": "2026-08-30", "Stakes_Claude": "2-1-3:100", "Strategy_Claude": "claude-v1"},
            ],
        )

        codex = model_feedback(self.data_dir, "2026-09-01", self.records, "codex")
        claude = model_feedback(self.data_dir, "2026-09-01", self.records, "claude")

        self.assertEqual(codex["settled_count"], 1)
        self.assertEqual(codex["all_time"]["hits"], 1)
        self.assertEqual(claude["settled_count"], 1)
        self.assertEqual(claude["all_time"]["hits"], 0)
        self.assertNotIn("codex-v1", claude["strategy_comparison"])

    def test_history_excludes_target_date_and_future(self) -> None:
        self._write_csv(
            "daily_history_results.csv",
            ["ID", "Date", "Venue", "R", "Result", "Payout"],
            [
                {"ID": "past", "Date": "2026-08-31", "Venue": "戸田", "R": "1", "Result": "1-2-3", "Payout": "1000"},
                {"ID": "target", "Date": "2026-09-01", "Venue": "戸田", "R": "2", "Result": "2-1-3", "Payout": "1200"},
                {"ID": "future", "Date": "2026-09-02", "Venue": "戸田", "R": "3", "Result": "3-1-2", "Payout": "1300"},
            ],
        )
        boat_rows = []
        for race_id in ("past", "target", "future"):
            for lane in range(1, 7):
                boat_rows.append({"ID": race_id, "Lane": str(lane), "WinRate": str(7 - lane), "Rank": "A1"})
        self._write_csv(
            "daily_raw_race_data.csv",
            ["ID", "Lane", "WinRate", "Rank"],
            boat_rows,
        )

        records = load_history_records(self.data_dir, "2026-09-01")
        self.assertEqual([row["race_id"] for row in records], ["past"])


if __name__ == "__main__":
    unittest.main()
