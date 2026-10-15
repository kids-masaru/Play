"""ボートレースのモデル別フィードバックと時系列ガードを確認する。"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from codex_learning import (
    build_model_learning_context,
    format_local_learning_context,
    load_history_records,
    model_feedback,
)


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
            },
            {
                "race_id": "qwen-race",
                "date": "2026-09-08",
                "venue": "戸田",
                "r": 2,
                "result": "2-1-3",
                "payout": 1200,
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

    def test_local_learned_models_use_only_their_own_feedback(self) -> None:
        cases = [
            ("gemma_ft", "daily_gemma_predictions.csv", "Stakes_GemmaFT", "Strategy_GemmaFT", "past-race", "2026-08-30", "2026-09-01", "1-2-3:100", 1),
            ("qwen_claude", "daily_gemma_claude_predictions.csv", "Stakes_GemmaClaude", "Strategy_GemmaClaude", "qwen-race", "2026-09-08", "2026-09-10", "2-1-3:100", 1),
            ("qwen_grok_x", "daily_gemma_grok_x_predictions.csv", "Stakes_GemmaGrokX", "Strategy_GemmaGrokX", "qwen-race", "2026-09-08", "2026-09-10", "3-1-2:100", 0),
        ]
        for model_key, filename, stakes_column, strategy_column, race_id, prediction_date, target_date, stakes, expected_hits in cases:
            self._write_csv(
                filename,
                ["RaceID", "Date", stakes_column, strategy_column],
                [
                    {
                        "RaceID": "past-race",
                        "Date": "2026-08-30",
                        stakes_column: "1-2-3:100",
                        strategy_column: "old-model",
                    },
                    {
                        "RaceID": race_id,
                        "Date": prediction_date,
                        stakes_column: stakes,
                        strategy_column: f"{model_key}-v1",
                    },
                ] if model_key.startswith("qwen_") else [{
                    "RaceID": race_id,
                    "Date": prediction_date,
                    stakes_column: stakes,
                    strategy_column: f"{model_key}-v1",
                }],
            )

            feedback = model_feedback(self.data_dir, target_date, self.records, model_key)
            self.assertEqual(feedback["settled_count"], 1)
            self.assertEqual(feedback["all_time"]["hits"], expected_hits)
            self.assertEqual(feedback["recent_results"][0]["race_id"], race_id)

    def test_local_prompt_contains_previous_results_and_similar_races(self) -> None:
        self._write_csv(
            "daily_history_results.csv",
            ["ID", "Date", "Venue", "R", "Result", "Payout"],
            [{"ID": "qwen-race", "Date": "2026-09-08", "Venue": "戸田", "R": "1", "Result": "1-2-3", "Payout": "1000"}],
        )
        self._write_csv(
            "daily_raw_race_data.csv",
            ["ID", "Lane", "WinRate", "Rank"],
            [
                {"ID": "qwen-race", "Lane": str(lane), "WinRate": str(7 - lane), "Rank": "A1"}
                for lane in range(1, 7)
            ],
        )
        self._write_csv(
            "daily_gemma_claude_predictions.csv",
            ["RaceID", "Date", "Stakes_GemmaClaude", "Strategy_GemmaClaude"],
            [{
                "RaceID": "qwen-race",
                "Date": "2026-09-08",
                "Stakes_GemmaClaude": "1-2-3:100",
                "Strategy_GemmaClaude": "feedback-test",
            }],
        )
        target_race = {
            "race_id": "target-race",
            "venue": "戸田",
            "r": 1,
            "wind_speed": "1m",
            "wave": "1cm",
            "boats": [
                {"lane": lane, "win_rate": 7 - lane, "rank": "A1"}
                for lane in range(1, 7)
            ],
        }

        context = build_model_learning_context(
            self.data_dir, "2026-09-10", [target_race], "qwen_claude"
        )
        prompt_section = format_local_learning_context(context, "target-race")

        self.assertIn("自分の確定結果1レース", prompt_section)
        self.assertIn("qwen-race: 的中", prompt_section)
        self.assertIn("類似レース1件", prompt_section)
        self.assertNotIn("target-race: 的中", prompt_section)


if __name__ == "__main__":
    unittest.main()
