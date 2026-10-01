"""Jev組合せ実験の事後採点を確認する。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jev_pairing_performance  # noqa: E402
import jev_shadow  # noqa: E402


class JevPairingPerformanceTest(unittest.TestCase):
    def test_report_separates_raw_portfolio_and_jev_selection(self) -> None:
        common = {
            "race_id": "r1",
            "date": "2026-09-30",
            "strategy_version": jev_shadow.STRATEGY_VERSION,
            "experiment_version": jev_shadow.EXPERIMENT_VERSION,
        }
        raw = {
            **common,
            "experiment_id": "codex_raw",
            "decision_source": "raw_model",
            "selected_candidate": "1-2-3",
            "raw_picks": [
                {"combo": "1-2-3", "stake_yen": 100},
                {"combo": "1-3-2", "stake_yen": 100},
            ],
        }
        selected = {
            **common,
            "experiment_id": "codex_jev",
            "decision_source": "jev",
            "selected_candidate": "1-3-2",
            "candidate_snapshot": [
                {"combo": "1-3-2", "total_proposed_stake_yen": 100}
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            history_path = temp / "history.jsonl"
            results_path = temp / "results.csv"
            jev_shadow.append_history(history_path, raw)
            jev_shadow.append_history(history_path, selected)
            results_path.write_text(
                "ID,Date,Result,Payout\n"
                "r1,2026-09-30,1-2-3,1000\n",
                encoding="utf-8",
            )

            report = jev_pairing_performance.build_report(
                history_path, results_path
            )

        self.assertEqual(report["latest_result_date"], "2026-09-30")
        self.assertEqual(
            report["arms"]["codex_raw"]["raw_portfolio"]["profit_yen"], 800
        )
        self.assertEqual(
            report["arms"]["codex_raw"]["forced_selected"]["profit_yen"], 900
        )
        self.assertEqual(
            report["arms"]["codex_jev"]["forced_selected"]["profit_yen"], -100
        )


if __name__ == "__main__":
    unittest.main()
