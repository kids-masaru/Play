"""実収支と高配当ストレス指標が全集計で同じ定義になることを確認する。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jev_pairing_performance as jpp  # noqa: E402
import model_performance as mp  # noqa: E402
import paired_stats  # noqa: E402


ROWS = [
    {"date": "2026-10-01", "id": "A", "invest": 500, "return": 5000, "profit": 4500, "hit": True},
    {"date": "2026-10-02", "id": "B", "invest": 500, "return": 0, "profit": -500, "hit": False},
    {"date": "2026-10-03", "id": "C", "invest": 500, "return": 250, "profit": -250, "hit": True},
]


class RobustnessMetricsTest(unittest.TestCase):
    def test_real_result_and_stress_result_are_separate(self) -> None:
        metric = paired_stats.robustness_metrics(ROWS)
        self.assertEqual(metric["profit_yen"], 3750)
        self.assertEqual(metric["roi_pct"], 350.0)
        self.assertEqual(metric["roi_without_largest_win_pct"], 25.0)
        self.assertEqual(metric["roi_without_top3_wins_pct"], 0.0)
        self.assertEqual(metric["largest_return_share_pct"], 95.2)
        self.assertEqual(metric["top3_return_share_pct"], 100.0)
        self.assertEqual(metric["max_drawdown_yen"], 750)
        self.assertEqual(metric["longest_losing_streak"], 1)

    def test_no_hit_has_no_exclusion_metric(self) -> None:
        metric = paired_stats.robustness_metrics([
            {"invest": 100, "return": 0},
            {"invest": 100, "return": 0},
        ])
        self.assertEqual(metric["roi_pct"], 0.0)
        self.assertIsNone(metric["roi_without_largest_win_pct"])
        self.assertIsNone(metric["largest_return_share_pct"])
        self.assertEqual(metric["longest_losing_streak"], 2)

    def test_model_and_jev_use_the_same_definition(self) -> None:
        model_metric = mp._metrics(ROWS)
        wrapped = [{"forced_selected": row} for row in ROWS]
        jev_metric = jpp.metrics(wrapped, "forced_selected")
        self.assertEqual(model_metric["roi_without_largest_win"], 25.0)
        self.assertEqual(jev_metric["roi_without_largest_win_pct"], 25.0)
        self.assertEqual(model_metric["largest_return_share"], jev_metric["largest_return_share_pct"])


if __name__ == "__main__":
    unittest.main()
