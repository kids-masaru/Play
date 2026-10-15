"""Claude予測のスキーマ受け渡しと、不正レースだけを除外する保存処理を確認する。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_claude_predictions as gcp  # noqa: E402


def _race(race_id: str) -> dict:
    return {"race_id": race_id, "date": "2026-10-15", "venue": "三国", "r": 1}


def _item(race_id: str, picks: list[str]) -> dict:
    return {"race_id": race_id, "picks": picks, "explanation": "テスト"}


GOOD = ["1-2-3", "1-2-4", "1-3-2", "1-3-4", "2-1-3"]


class ClaudeSchemaTest(unittest.TestCase):
    def test_schema_has_no_meta_schema_url(self) -> None:
        # Claude CLIが解決できない "$schema" は渡さない
        schema = gcp._load_schema()
        self.assertNotIn("$schema", schema)
        self.assertIn("predictions", schema["properties"])


class ClaudeSaveRowsTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(gcp, "write_rows")
        self.write_rows = patcher.start()
        self.addCleanup(patcher.stop)
        self.context = {"historical_results_used": 0, "model_feedback": {"settled_count": 0}}

    def test_invalid_race_is_dropped_and_others_saved(self) -> None:
        races = {"A": _race("A"), "B": _race("B")}
        result = {"predictions": [_item("A", GOOD), _item("B", GOOD[:4])]}
        existing: dict = {}
        saved = gcp.save_rows(existing, races, result, self.context)
        self.assertEqual(saved, 1)
        self.assertIn("A", existing)
        self.assertNotIn("B", existing)

    def test_missing_race_does_not_block_others(self) -> None:
        races = {"A": _race("A"), "B": _race("B")}
        result = {"predictions": [_item("A", GOOD)]}
        existing: dict = {}
        self.assertEqual(gcp.save_rows(existing, races, result, self.context), 1)

    def test_all_invalid_raises(self) -> None:
        races = {"A": _race("A")}
        result = {"predictions": [_item("A", GOOD[:3])]}
        with self.assertRaises(ValueError):
            gcp.save_rows({}, races, result, self.context)
        self.write_rows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
