"""心得集の振り返り（たすき掛け・モデル別分離・未来情報防止・障害分離）を確認する。"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import playbook as pb  # noqa: E402
import playbook_reflect as pr  # noqa: E402


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


RACES = [
    # (race_id, date, result, payout)
    ("20261013_平和島_1", "2026-10-13", "1-2-3", 1500),
    ("20261014_平和島_1", "2026-10-14", "1-3-2", 2000),
    ("20261015_平和島_1", "2026-10-15", "2-1-3", 3000),
    ("20261016_平和島_1", "2026-10-16", "1-2-3", 1200),  # 対象日当日（使ってはいけない）
]


class ReflectTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data_dir = root / "data"
        self.base_dir = root / "playbooks"
        self.data_dir.mkdir()
        _write_csv(
            self.data_dir / "daily_history_results.csv",
            ["Date", "Venue", "R", "ID", "Result", "Payout"],
            [{"Date": d, "Venue": "平和島", "R": 1, "ID": rid, "Result": res, "Payout": pay} for rid, d, res, pay in RACES],
        )
        _write_csv(
            self.data_dir / "daily_raw_race_data.csv",
            ["ID", "Lane", "WinRate", "Rank"],
            [
                {"ID": rid, "Lane": lane, "WinRate": 7.0 if lane == 1 else 5.0, "Rank": "A1" if lane == 1 else "B1"}
                for rid, *_ in RACES
                for lane in range(1, 7)
            ],
        )
        picks_hit = "1-2-3:100, 1-3-2:100, 2-1-3:100, 1-2-4:100, 1-4-2:100"
        _write_csv(
            self.data_dir / "daily_codex_predictions.csv",
            ["RaceID", "Date", "Venue", "R", "Prediction_Codex", "Log_Codex", "Stakes_Codex", "Strategy_Codex"],
            [
                {"RaceID": rid, "Date": d, "Venue": "平和島", "R": 1, "Log_Codex": "CODEX理由", "Stakes_Codex": picks_hit}
                for rid, d, *_ in RACES
            ],
        )
        _write_csv(
            self.data_dir / "daily_claude_predictions.csv",
            ["RaceID", "Date", "Venue", "R", "Prediction_Claude", "Log_Claude", "Stakes_Claude", "Strategy_Claude"],
            [
                {
                    "RaceID": rid,
                    "Date": d,
                    "Venue": "平和島",
                    "R": 1,
                    "Log_Claude": "CLAUDE理由",
                    "Stakes_Claude": "4-5-6:100, 4-6-5:100, 5-4-6:100, 5-6-4:100, 6-5-4:100",
                }
                for rid, d, *_ in RACES
            ],
        )
        self.calls: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def fake_call(self, ops=None, summary="要点"):
        def call(reflector: str, prompt: str) -> dict:
            self.calls.append((reflector, prompt))
            return {
                "summary": summary,
                "ops": ops if ops is not None else [
                    {
                        "op": "add",
                        "id": None,
                        "text": "平和島1Rで1号艇A1なら1頭を厚く",
                        "reason": None,
                        "evidence_race_ids": ["20261014_平和島_1", "架空のレース"],
                    }
                ],
            }

        return call

    def run_reflect(self, models, target="2026-10-16", call=None, **kwargs):
        return pr.run(
            target,
            models,
            data_dir=self.data_dir,
            base_dir=self.base_dir,
            call=call or self.fake_call(),
            **kwargs,
        )


class CollectMaterialTest(ReflectTestBase):
    def test_only_own_predictions_before_target_date(self) -> None:
        records = pr.load_history_records(self.data_dir, "2026-10-16")
        settled = pr.collect_settled(self.data_dir, "2026-10-16", "codex", records)
        self.assertEqual([r["date"] for r in settled], ["2026-10-13", "2026-10-14", "2026-10-15"])
        self.assertTrue(all(r["explanation"] == "CODEX理由" for r in settled))
        first = settled[0]
        self.assertTrue(first["hit"])
        self.assertEqual(first["stake_yen"], 500)
        self.assertEqual(first["profit"], 1500 - 500)

    def test_select_material_takes_only_new_and_latest(self) -> None:
        rows = [{"date": f"2026-10-{d:02d}", "race_id": str(d)} for d in range(1, 11)]
        self.assertEqual([r["race_id"] for r in pr.select_material(rows, "2026-10-08")], ["9", "10"])
        self.assertEqual([r["race_id"] for r in pr.select_material(rows, None, limit=3)], ["8", "9", "10"])
        self.assertEqual(pr.select_material(rows, "2026-10-10"), [])

    def test_summarize_material(self) -> None:
        summary = pr.summarize_material([
            {"hit": True, "stake_yen": 500, "profit": 1000},
            {"hit": False, "stake_yen": 500, "profit": -500},
        ])
        self.assertEqual(summary["races"], 2)
        self.assertEqual(summary["hit_rate_pct"], 50.0)
        self.assertEqual(summary["roi_pct"], 150.0)


class ReflectRunTest(ReflectTestBase):
    def test_cross_assignment_and_model_isolation(self) -> None:
        results = self.run_reflect(["codex", "claude"])
        self.assertEqual([r["status"] for r in results], ["done", "done"])
        reflectors = [c[0] for c in self.calls]
        self.assertEqual(reflectors, ["claude", "codex"])  # たすき掛け
        codex_prompt, claude_prompt = self.calls[0][1], self.calls[1][1]
        # 他モデルの買い目・理由は見せない
        self.assertIn("CODEX理由", codex_prompt)
        self.assertNotIn("CLAUDE理由", codex_prompt)
        self.assertNotIn("4-5-6", codex_prompt)
        self.assertIn("CLAUDE理由", claude_prompt)
        self.assertNotIn("CODEX理由", claude_prompt)
        # 対象日当日のレースは材料に入れない
        self.assertNotIn("20261016_平和島_1", codex_prompt)

    def test_done_writes_playbook_changes_snapshot_and_reflection(self) -> None:
        result = self.run_reflect(["codex"])[0]
        self.assertEqual(result["applied"], 1)
        self.assertEqual(result["result_last_date"], "2026-10-15")
        book = pb.load_playbook("codex", self.base_dir)
        self.assertEqual(book["items"][0]["text"], "平和島1Rで1号艇A1なら1頭を厚く")
        # 材料に無いレースIDは根拠から外す
        self.assertEqual(book["items"][0]["evidence_race_ids"], ["20261014_平和島_1"])
        self.assertTrue((self.base_dir / "changes.jsonl").is_file())
        snap = pb.load_snapshot("codex", "2026-10-16", self.base_dir)
        self.assertEqual(snap["snapshot_date"], "2026-10-16")
        reflection = json.loads(
            (self.base_dir / "reflections" / "codex" / "2026-10-16.json").read_text(encoding="utf-8")
        )
        self.assertEqual(reflection["reflector"], "claude")
        self.assertEqual(len(reflection["material_race_ids"]), 3)
        state = json.loads((self.base_dir / "reflect_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["codex"]["result_last_date"], "2026-10-15")

    def test_same_day_is_skipped_and_next_day_uses_only_new_results(self) -> None:
        self.run_reflect(["codex"])
        self.assertEqual(self.run_reflect(["codex"])[0]["status"], "skipped")
        self.assertEqual(len(self.calls), 1)
        # 翌日（17日）は16日の結果だけが新しい材料
        result = self.run_reflect(["codex"], target="2026-10-17", call=self.fake_call(ops=[]))[0]
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["material_races"], 1)
        self.assertIn("20261016_平和島_1", self.calls[-1][1])
        self.assertNotIn("20261015_平和島_1", self.calls[-1][1])

    def test_force_same_day_reuses_same_material(self) -> None:
        self.run_reflect(["codex"])
        result = self.run_reflect(["codex"], force=True, call=self.fake_call(ops=[]))[0]
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["material_races"], 3)

    def test_no_new_results_does_not_call_reflector(self) -> None:
        self.run_reflect(["codex"])
        # 16日の結果がまだ無い状態で17日を振り返る想定：結果CSVから16日を消す
        _write_csv(
            self.data_dir / "daily_history_results.csv",
            ["Date", "Venue", "R", "ID", "Result", "Payout"],
            [{"Date": d, "Venue": "平和島", "R": 1, "ID": rid, "Result": res, "Payout": pay} for rid, d, res, pay in RACES[:3]],
        )
        before = len(self.calls)
        result = self.run_reflect(["codex"], target="2026-10-17")[0]
        self.assertEqual(result["status"], "no_material")
        self.assertEqual(len(self.calls), before)
        self.assertIsNotNone(pb.load_snapshot("codex", "2026-10-17", self.base_dir))

    def test_failure_keeps_playbook_and_other_models_continue(self) -> None:
        def call(reflector: str, prompt: str) -> dict:
            if reflector == "claude":
                raise pr.ReflectorError("使用枠切れ")
            return self.fake_call()(reflector, prompt)

        results = self.run_reflect(["codex", "claude"], call=call)
        self.assertEqual([r["status"] for r in results], ["failed", "done"])
        self.assertIn("使用枠切れ", results[0]["error"])
        self.assertEqual(pb.load_playbook("codex", self.base_dir)["items"], [])
        self.assertIsNone(pb.load_snapshot("codex", "2026-10-16", self.base_dir))
        # 失敗したモデルは同じ日に再実行すると振り返り直せる
        self.assertEqual(self.run_reflect(["codex"])[0]["status"], "done")

    def test_rewrite_attempt_is_rejected_without_changes(self) -> None:
        ops = [{"op": "add", "id": None, "text": f"心得{i}", "reason": None, "evidence_race_ids": []} for i in range(6)]
        result = self.run_reflect(["codex"], call=self.fake_call(ops=ops))[0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(pb.load_playbook("codex", self.base_dir)["items"], [])

    def test_dry_run_writes_nothing(self) -> None:
        result = self.run_reflect(["codex"], dry_run=True)[0]
        self.assertEqual(result["status"], "dry_run")
        self.assertGreater(result["prompt_chars"], 0)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.base_dir.exists())


class OutputParseTest(unittest.TestCase):
    def test_structured_output_wrapper(self) -> None:
        stdout = json.dumps({"type": "result", "structured_output": {"summary": "s", "ops": []}})
        self.assertEqual(pr.extract_claude_output(stdout), {"summary": "s", "ops": []})

    def test_result_text_with_code_fence(self) -> None:
        inner = json.dumps({"summary": "s", "ops": [{"op": "add"}]}, ensure_ascii=False)
        stdout = json.dumps({"result": f"```json\n{inner}\n```"})
        self.assertEqual(pr.extract_claude_output(stdout)["ops"], [{"op": "add"}])

    def test_missing_ops_raises(self) -> None:
        with self.assertRaises(pr.ReflectorError):
            pr.extract_claude_output(json.dumps({"result": "わかりません"}))

    def test_main_rejects_unknown_model(self) -> None:
        self.assertEqual(pr.main(["--models", "gemini", "--dry-run"]), 2)


if __name__ == "__main__":
    unittest.main()
