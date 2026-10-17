"""心得集あり版の予測（同じ入力＋心得集・使用ID・障害分離・保存形式）を確認する。"""

from __future__ import annotations

import csv
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import playbook as pb  # noqa: E402
import playbook_predict as pp  # noqa: E402

TARGET = "2026-10-18"


def _race(rid: str, r: int) -> dict:
    return {
        "race_id": rid,
        "date": TARGET,
        "venue": "平和島",
        "r": r,
        "weather": "晴",
        "wind_speed": "2m",
        "wind_dir": "向かい風",
        "wave": "2cm",
        "water_temp": "20℃",
        "boats": [
            {"lane": lane, "name": f"選手{lane}", "rank": "A1" if lane == 1 else "B1", "win_rate": 6.0, "motor_no": "1", "weight": 52, "ex_time": 6.8}
            for lane in range(1, 7)
        ],
        "odds_top": [],
    }


RACES = [_race("20261018_平和島_1", 1), _race("20261018_平和島_2", 2)]
FIVE = ["1-2-3", "1-3-2", "1-2-4", "1-4-2", "2-1-3"]


def _read(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class PlaybookPredictTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data_dir = root / "data"
        self.base_dir = root / "playbooks"
        self.data_dir.mkdir()
        self.prompts: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _seed(self, model_key: str, day: str = TARGET, texts=("1号艇A1なら1頭を厚く",)) -> None:
        book = pb.empty_playbook(model_key)
        book = pb.apply_ops(
            book,
            [{"op": "add", "text": t} for t in texts],
            target_date=day,
            result_last_date=None,
            reflector="test",
        )["playbook"]
        pb.save_snapshot(book, day, self.base_dir)

    def _strong(self, predictions):
        def call(model_key: str, prompt: str) -> dict:
            self.prompts.append((model_key, prompt))
            return {"predictions": predictions}

        return call

    def _run(self, model_key: str, **kwargs):
        return pp.predict_model(
            model_key, TARGET, RACES, data_dir=self.data_dir, base_dir=self.base_dir, **kwargs
        )

    def test_empty_playbook_does_not_predict(self) -> None:
        result = self._run("codex", strong_call=self._strong([]))
        self.assertEqual(result["status"], "empty_playbook")
        self.assertEqual(self.prompts, [])
        self.assertFalse((self.data_dir / "daily_codex_playbook_predictions.csv").exists())

    def test_codex_prompt_is_existing_prompt_plus_playbook(self) -> None:
        self._seed("codex")
        predictions = [
            {"race_id": RACES[0]["race_id"], "picks": FIVE, "explanation": "理由", "used_playbook_ids": ["codex-001", "codex-999"]},
            {"race_id": RACES[1]["race_id"], "picks": FIVE[:4], "explanation": "4点しかない", "used_playbook_ids": []},
        ]
        result = self._run("codex", strong_call=self._strong(predictions))
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["saved"], 1)  # 5点に満たないレースだけ除外
        prompt = self.prompts[0][1]
        self.assertIn("RACE_DATA_JSON", prompt)  # 既存の指示文をそのまま使う
        self.assertIn("HISTORICAL_LEARNING_JSON", prompt)
        self.assertIn("PLAYBOOK_TEXT", prompt)
        self.assertIn("[codex-001] 1号艇A1なら1頭を厚く", prompt)
        self.assertIn("including used_playbook_ids", prompt)

        rows = _read(self.data_dir / "daily_codex_playbook_predictions.csv")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["Stakes_CodexPB"], ", ".join(f"{p}:100" for p in FIVE))
        self.assertEqual(row["PlaybookUsedIds"], "codex-001")  # 渡していないIDは捨てる
        self.assertEqual(row["PlaybookDate"], TARGET)
        self.assertEqual(row["PlaybookItems"], "1")
        self.assertEqual(row["Strategy_CodexPB"], pp.STRATEGY_VERSION)
        snap = pb.load_snapshot("codex", TARGET, self.base_dir)
        self.assertEqual(row["PlaybookHash"], snap["hash"])

    def test_rerun_skips_saved_races_and_force_redoes(self) -> None:
        self._seed("claude")
        predictions = [
            {"race_id": race["race_id"], "picks": FIVE, "explanation": "理由", "used_playbook_ids": []}
            for race in RACES
        ]
        self.assertEqual(self._run("claude", strong_call=self._strong(predictions))["saved"], 2)
        self.assertEqual(self._run("claude", strong_call=self._strong(predictions))["status"], "up_to_date")
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self._run("claude", strong_call=self._strong(predictions), force=True)["saved"], 2)

    def test_uses_previous_snapshot_when_today_missing(self) -> None:
        self._seed("claude", day="2026-10-16")
        predictions = [{"race_id": RACES[0]["race_id"], "picks": FIVE, "explanation": "", "used_playbook_ids": []}]
        result = self._run("claude", strong_call=self._strong(predictions))
        self.assertEqual(result["playbook_date"], "2026-10-16")

    def test_strong_failure_is_isolated(self) -> None:
        self._seed("codex")

        def call(model_key: str, prompt: str) -> dict:
            raise RuntimeError("使用枠切れ")

        result = self._run("codex", strong_call=call)
        self.assertEqual(result["status"], "failed")
        self.assertIn("使用枠切れ", result["error"])
        self.assertFalse((self.data_dir / "daily_codex_playbook_predictions.csv").exists())

    def test_local_model_appends_playbook_and_picks_up_ids(self) -> None:
        self._seed("qwen_claude")

        def generate(prompt: str, model: str) -> str:
            self.prompts.append((model, prompt))
            if "平和島 2R" in prompt:
                return "[推論]\nよく分からない"  # 買い目なし → 保存しない
            return "[推論]\nqwen_claude-001 に従い1頭\n[買い目]\n1-2-3\n1-3-2\n1-2-4"

        result = self._run("qwen_claude", local_generate=generate)
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["saved"], 1)
        model, prompt = self.prompts[0]
        self.assertEqual(model, "qwen-boat-claude:1.7b")
        self.assertIn("【出走表】", prompt)  # 既存のローカル用入力をそのまま使う
        self.assertTrue(prompt.rstrip().endswith("1号艇A1なら1頭を厚く"))
        rows = _read(self.data_dir / "daily_qwen_claude_playbook_predictions.csv")
        self.assertEqual(rows[0]["Stakes_QwenClaudePB"], "1-2-3:100, 1-3-2:100, 1-2-4:100")
        self.assertEqual(rows[0]["PlaybookUsedIds"], "qwen_claude-001")

    def test_main_refuses_when_input_is_not_today(self) -> None:
        with (
            patch.object(pp, "load_input", return_value=("2000-01-01", RACES)),
            patch.object(pp, "predict_model") as predict,
        ):
            self.assertEqual(pp.main([]), 0)
        predict.assert_not_called()

    def test_main_rejects_unknown_model(self) -> None:
        self.assertEqual(pp.main(["--models", "grok"]), 2)


class MorningBatchHookTest(unittest.TestCase):
    def test_runs_at_end_of_morning_batch(self) -> None:
        bat = (ROOT / "run_morning.bat").read_text(encoding="ascii")
        self.assertIn("python playbook_predict.py", bat)
        # 既存の予測・公開（battle update）と CLV の後で動かし、既存を遅らせない
        self.assertLess(bat.index("python update_battle_dashboard.py"), bat.index("python playbook_predict.py"))
        self.assertLess(bat.index("python compute_clv.py"), bat.index("python playbook_predict.py"))


if __name__ == "__main__":
    unittest.main()
