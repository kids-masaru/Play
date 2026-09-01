"""Claude失敗時も集計・公開処理まで進むことを確認する。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "toto"))

import update_battle_dashboard  # noqa: E402
from toto import run_toto_weekly  # noqa: E402


class ClaudeOrchestrationTest(unittest.TestCase):
    def test_boat_continues_after_claude_failure(self) -> None:
        calls = []

        def fake_run(script, allow_fail=False, extra_args=None):
            calls.append((script, allow_fail, extra_args))
            return script != "generate_claude_predictions.py"

        argv = [
            "update_battle_dashboard.py",
            "--no-push",
            "--skip-gemini",
            "--skip-grok",
            "--skip-codex",
            "--skip-gemma",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(update_battle_dashboard, "copy_sources"),
            patch.object(update_battle_dashboard, "run_py", side_effect=fake_run),
            patch.object(update_battle_dashboard, "publish") as publish,
        ):
            update_battle_dashboard.main()

        self.assertIn(("generate_claude_predictions.py", True, None), calls)
        self.assertIn(("model_performance.py", False, None), calls)
        publish.assert_called_once_with(no_push=True)

    def test_toto_continues_after_claude_failure(self) -> None:
        calls = []

        def fake_run(script, *args, allow_fail=False):
            calls.append((script, args, allow_fail))
            return script != "toto/predict_claude.py"

        argv = [
            "run_toto_weekly.py",
            "--no-push",
            "--skip-gemini",
            "--skip-codex",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(run_toto_weekly, "round_numbers", return_value=[1649]),
            patch.object(run_toto_weekly, "run_py", side_effect=fake_run),
            patch.object(run_toto_weekly.os.path, "exists", return_value=False),
            patch.object(run_toto_weekly, "publish") as publish,
        ):
            result = run_toto_weekly.main()

        self.assertEqual(result, 1)
        self.assertIn(("toto/predict_claude.py", ("1649",), True), calls)
        self.assertIn(("toto/generate_toto_data.py", (), True), calls)
        publish.assert_called_once_with(no_push=True)


if __name__ == "__main__":
    unittest.main()
