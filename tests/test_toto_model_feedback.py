"""totoのモデル別自己フィードバックと対象回ガードを確認する。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOTO_DIR = Path(__file__).resolve().parents[1] / "toto"
sys.path.insert(0, str(TOTO_DIR))

from model_feedback import load_model_feedback  # noqa: E402


class TotoModelFeedbackTest(unittest.TestCase):
    def test_model_and_round_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            match = {"date": "2026-08-30", "home": "A", "away": "B"}
            settled = {"results": [{**match, "actual": "H"}]}
            (data_dir / "settled_100.json").write_text(
                json.dumps(settled), encoding="utf-8"
            )
            (data_dir / "codex_round_100.json").write_text(
                json.dumps({"round": 100, "predictions": [{**match, "pick": "H"}]}),
                encoding="utf-8",
            )
            (data_dir / "claude_round_100.json").write_text(
                json.dumps({"round": 100, "predictions": [{**match, "pick": "A"}]}),
                encoding="utf-8",
            )
            # 対象回と同じ回は、settledファイルがあっても学習へ入れない。
            (data_dir / "codex_round_101.json").write_text(
                json.dumps({"round": 101, "predictions": [{**match, "pick": "H"}]}),
                encoding="utf-8",
            )
            (data_dir / "settled_101.json").write_text(
                json.dumps(settled), encoding="utf-8"
            )

            codex = load_model_feedback(data_dir, 101, "codex")
            claude = load_model_feedback(data_dir, 101, "claude")

            self.assertEqual(codex["settled_predictions"], 1)
            self.assertEqual(codex["hits"], 1)
            self.assertEqual(claude["settled_predictions"], 1)
            self.assertEqual(claude["hits"], 0)
            self.assertEqual(codex["recent_misses"], [])
            self.assertEqual(len(claude["recent_misses"]), 1)


if __name__ == "__main__":
    unittest.main()
