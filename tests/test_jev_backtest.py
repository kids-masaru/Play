"""Jev時系列バックテストの未来情報防止と採点規則を確認する。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jev_backtest  # noqa: E402


class JevBacktestTest(unittest.TestCase):
    def test_git_snapshot_commits_uses_latest_battle_snapshot_per_day(self) -> None:
        log = "\n".join(
            [
                "new\x1f2026-09-17T10:00:00+09:00\x1fAuto-update battle dashboard: new",
                "other\x1f2026-09-17T09:00:00+09:00\x1fdocs: unrelated",
                "old\x1f2026-09-17T08:00:00+09:00\x1fAuto-update battle dashboard: old",
                "outside\x1f2026-09-14T10:00:00+09:00\x1fAuto-update battle dashboard: outside",
            ]
        )

        with patch.object(jev_backtest, "_git_text", return_value=log):
            snapshots = jev_backtest.git_snapshot_commits(
                "2026-09-15", "2026-09-30"
            )

        self.assertEqual(list(snapshots), ["2026-09-17"])
        self.assertEqual(snapshots["2026-09-17"]["commit"], "new")

    def test_state_hash_is_stable_across_key_order(self) -> None:
        first = {"race": {"date": "2026-09-17", "race_id": "r1"}, "items": [1, 2]}
        second = {"items": [1, 2], "race": {"race_id": "r1", "date": "2026-09-17"}}

        self.assertEqual(
            jev_backtest.state_sha256(first), jev_backtest.state_sha256(second)
        )

    def test_candidate_ids_requires_two_models_and_result(self) -> None:
        predictions = {
            "r1": {"stakes_grok": "1-2-3:100", "stakes_codex": "1-2-3:100"},
            "r2": {"stakes_grok": "1-2-3:100"},
            "r3": {"stakes_grok": "1-2-3:100", "stakes_codex": "1-3-2:100"},
        }
        results = {
            "r1": {"date": "2026-09-15"},
            "r2": {"date": "2026-09-15"},
        }

        self.assertEqual(
            jev_backtest.candidate_ids(
                predictions, results, "2026-09-15", "2026-09-30"
            ),
            ["r1"],
        )

    def test_performance_snapshot_excludes_target_day(self) -> None:
        records = {model["key"]: [] for model in jev_backtest.model_performance.MODELS}
        records["stakes_grok"] = [
            {
                "id": "past",
                "date": "2026-09-14",
                "invest": 100,
                "return": 200,
                "profit": 100,
                "hit": True,
            },
            {
                "id": "same-day",
                "date": "2026-09-15",
                "invest": 100,
                "return": 0,
                "profit": -100,
                "hit": False,
            },
        ]

        snapshot = jev_backtest.performance_snapshot(records, "2026-09-15")
        grok = next(
            row
            for row in snapshot["periods"]["weekly"]["models"]
            if row["key"] == "stakes_grok"
        )

        self.assertEqual(snapshot["latest_result_date"], "2026-09-14")
        self.assertEqual(grok["n"], 1)
        self.assertEqual(grok["profit"], 100)

    def test_clv_snapshot_excludes_target_day(self) -> None:
        prediction_log = [
            {"RaceID": "past", "Date": "2026-09-14", "model": "grok", "combos": "1-2-3"},
            {"RaceID": "same", "Date": "2026-09-15", "model": "grok", "combos": "1-2-3"},
        ]
        morning = {
            "past": {"1-2-3": 10, "1-3-2": 20, "2-1-3": 30},
            "same": {"1-2-3": 10, "1-3-2": 20, "2-1-3": 30},
        }
        closing = {
            "past": {"1-2-3": 5, "1-3-2": 20, "2-1-3": 30},
            "same": {"1-2-3": 100, "1-3-2": 20, "2-1-3": 30},
        }

        snapshot = jev_backtest.clv_snapshot(
            prediction_log, morning, closing, "2026-09-15"
        )

        self.assertEqual(snapshot["models"]["grok"]["graded_races"], 1)
        self.assertGreater(snapshot["models"]["grok"]["avg_clv_pp"], 0)

    def test_skip_gate_avoids_baseline_loss(self) -> None:
        state = {
            "model_predictions": [
                {"picks": [{"combo": "1-2-3", "stake_yen": 100}]},
                {"picks": [{"combo": "1-3-2", "stake_yen": 100}]},
            ]
        }
        decision = {
            "action": "skip",
            "selected_candidate": "",
            "candidate_snapshot": [],
        }
        result = {
            "race_id": "r1",
            "date": "2026-09-15",
            "result": "2-1-3",
            "payout": 1000,
        }

        evaluated = jev_backtest.evaluate_record(decision, state, result)

        self.assertEqual(evaluated["baseline"]["profit"], -200)
        self.assertEqual(evaluated["jev_gate"]["profit"], 0)

    def test_selected_candidate_uses_aggregate_proposed_stake(self) -> None:
        state = {
            "model_predictions": [
                {"picks": [{"combo": "1-2-3", "stake_yen": 100}]},
                {"picks": [{"combo": "1-2-3", "stake_yen": 100}]},
            ]
        }
        decision = {
            "action": "standard",
            "selected_candidate": "1-2-3",
            "answers": {
                "action": {
                    "probabilities": {"skip": 0.2, "small": 0.3, "standard": 0.5}
                }
            },
            "candidate_snapshot": [
                {"combo": "1-2-3", "total_proposed_stake_yen": 200}
            ],
        }
        state["candidates"] = [
            {"combo": "1-2-3", "total_proposed_stake_yen": 200}
        ]
        result = {
            "race_id": "r1",
            "date": "2026-09-15",
            "result": "1-2-3",
            "payout": 1000,
        }

        evaluated = jev_backtest.evaluate_record(decision, state, result)

        self.assertEqual(evaluated["jev_selected"]["invest"], 200)
        self.assertEqual(evaluated["jev_selected"]["return"], 2000)
        self.assertEqual(evaluated["buy_probability"], 0.8)
        self.assertEqual(evaluated["jev_candidate_forced"]["return"], 2000)

    def test_probability_gate_uses_predefined_threshold(self) -> None:
        rows = [
            {
                "buy_probability": 0.4,
                "baseline": {"invest": 100, "return": 200, "profit": 100, "hit": True},
            },
            {
                "buy_probability": 0.2,
                "baseline": {"invest": 100, "return": 0, "profit": -100, "hit": False},
            },
        ]

        result = jev_backtest.probability_gate_metrics(rows, 0.3)

        self.assertEqual(result["purchased_races"], 1)
        self.assertEqual(result["profit_yen"], 100)

    def test_paired_bootstrap_uses_same_race_differences(self) -> None:
        rows = [
            {
                "first": {"profit": 100},
                "second": {"profit": 0},
            }
            for _ in range(10)
        ]

        result = jev_backtest.paired_bootstrap_difference(
            rows, "first", "second", iterations=100, seed=1
        )

        self.assertEqual(result["profit_difference_yen"], 1000)
        self.assertEqual(result["ci95_yen"], [1000, 1000])
        self.assertEqual(result["probability_first_better"], 1.0)

    def test_prepare_rejects_negative_api_limit_before_loading_files(self) -> None:
        args = SimpleNamespace(max_races=-1, pilot_size=30)

        with self.assertRaisesRegex(ValueError, "max-races"):
            jev_backtest.prepare(args)


if __name__ == "__main__":
    unittest.main()
