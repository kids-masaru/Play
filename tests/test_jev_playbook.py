"""E：心得集あり版を Jev 組合せ実験へ足した部分（jev_pairing_v2）を確認する。"""

from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jev_pairing_performance  # noqa: E402
import jev_shadow  # noqa: E402
import paired_stats  # noqa: E402


RACE = {
    "race_id": "20261020_桐生_1",
    "date": "2026-10-20",
    "ai_picks_codex": "1-2-3:100, 1-3-2:100",
    "ai_picks_gemini": "1-2-3:100",
    "ai_picks_codex_playbook": "2-1-3:100, 1-2-4:100",
    "odds_top": [{"combo": "1-2-3", "odds": 8.0}],
}
PERFORMANCE = {"periods": {"weekly": {"models": [{"key": "stakes_codex", "n": 40, "roi": 90.0}]}}}


def _args(**overrides: object) -> argparse.Namespace:
    values = {"dry_run": False, "endpoint": "", "model": "", "timeout": 1.0}
    values.update(overrides)
    return argparse.Namespace(**values)


def _arm(arm_id: str) -> dict:
    return next(arm for arm in jev_shadow.PAIRING_ARMS if arm["id"] == arm_id)


class SourceSeparationTest(unittest.TestCase):
    def test_all_models_jev_never_sees_playbook_picks(self) -> None:
        state = jev_shadow.build_race_state(RACE, PERFORMANCE, {})
        ids = [model["model_id"] for model in state["model_predictions"]]
        self.assertEqual(ids, ["gemini", "codex"])
        self.assertNotIn("2-1-3", [c["combo"] for c in state["candidates"]])

    def test_playbook_source_uses_own_picks_and_base_model_history(self) -> None:
        state = jev_shadow.build_race_state(RACE, PERFORMANCE, {}, source_ids=("codex_playbook",))
        [model] = state["model_predictions"]
        self.assertEqual(model["model_id"], "codex_playbook")
        self.assertEqual([p["combo"] for p in model["picks"]], ["2-1-3", "1-2-4"])
        # 成績は元のCodexと同じものを渡す（入力の差は心得集の有無だけ）
        self.assertEqual(model["weekly"]["n"], 40)

    def test_new_arms_exist_and_versions_are_compatible(self) -> None:
        ids = {arm["id"] for arm in jev_shadow.PAIRING_ARMS}
        for arm_id in ("codex_playbook_raw", "codex_playbook_jev", "claude_playbook_raw", "claude_playbook_jev"):
            self.assertIn(arm_id, ids)
        self.assertEqual(jev_shadow.EXPERIMENT_VERSION, "jev_pairing_v2")
        self.assertIn("jev_pairing_v1", jev_shadow.COMPATIBLE_EXPERIMENT_VERSIONS)


class PlaybookCsvTest(unittest.TestCase):
    def test_only_target_date_rows_are_attached_and_input_is_not_mutated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "daily_codex_playbook_predictions.csv").write_text(
                "RaceID,Date,Stakes_CodexPB\n"
                "r1,2026-10-20,1-2-3:100\n"
                "r2,2026-10-19,4-5-6:100\n",
                encoding="utf-8",
            )
            picks = jev_shadow.load_playbook_picks(folder, "2026-10-20")
        self.assertEqual(picks, {"r1": {"ai_picks_codex_playbook": "1-2-3:100"}})

        races = [{"race_id": "r1"}, {"race_id": "r2"}]
        attached = jev_shadow.attach_playbook_picks(races, picks)
        self.assertEqual(attached[0]["ai_picks_codex_playbook"], "1-2-3:100")
        self.assertNotIn("ai_picks_codex_playbook", races[0])
        self.assertIs(attached[1], races[1])

    def test_missing_folder_gives_no_picks(self) -> None:
        self.assertEqual(jev_shadow.load_playbook_picks(Path("does-not-exist"), "2026-10-20"), {})


class RawArmRetryTest(unittest.TestCase):
    def test_raw_playbook_arm_without_prediction_is_a_retryable_skip(self) -> None:
        race = {key: value for key, value in RACE.items() if key != "ai_picks_codex_playbook"}
        record, called = jev_shadow.build_arm_record(race, PERFORMANCE, {}, {}, _arm("codex_playbook_raw"), _args(), "")
        self.assertFalse(called)
        self.assertEqual(record["reason"], "source_model_prediction_missing")
        self.assertTrue(jev_shadow.is_retryable_skip(record))

    def test_raw_playbook_arm_with_prediction_records_all_picks(self) -> None:
        record, _ = jev_shadow.build_arm_record(RACE, PERFORMANCE, {}, {}, _arm("codex_playbook_raw"), _args(), "")
        self.assertEqual(record["decision_source"], "raw_model")
        self.assertEqual(record["experiment_version"], "jev_pairing_v2")
        self.assertEqual([p["combo"] for p in record["raw_picks"]], ["2-1-3", "1-2-4"])


class PlaybookEffectTest(unittest.TestCase):
    def _record(self, arm_id: str, race_id: str, version: str, combos: list[str]) -> dict:
        base = {
            "race_id": race_id,
            "date": "2026-10-19",
            "strategy_version": jev_shadow.STRATEGY_VERSION,
            "experiment_version": version,
            "experiment_id": arm_id,
        }
        if arm_id.endswith("_raw"):
            return {**base, "decision_source": "raw_model", "selected_candidate": combos[0] if combos else "",
                    "raw_picks": [{"combo": c, "stake_yen": 100} for c in combos]}
        return {**base, "decision_source": "jev", "selected_candidate": combos[0] if combos else "",
                "candidate_snapshot": [{"combo": c, "total_proposed_stake_yen": 100} for c in combos]}

    def test_v1_records_still_count_and_pairs_use_common_purchased_races(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            history = folder / "history.jsonl"
            # r1：両方買った → 比べる。r2：心得集側は予測なし → 比べない。codex_raw は v1 の記録
            for record in (
                self._record("codex_raw", "r1", "jev_pairing_v1", ["1-3-2"]),
                self._record("codex_playbook_raw", "r1", "jev_pairing_v2", ["1-2-3"]),
                self._record("codex_raw", "r2", "jev_pairing_v1", ["1-2-3"]),
                self._record("codex_playbook_raw", "r2", "jev_pairing_v2", []),
            ):
                jev_shadow.append_history(history, record)
            results = folder / "results.csv"
            results.write_text("ID,Date,Result,Payout\nr1,2026-10-19,1-2-3,1000\nr2,2026-10-19,1-2-3,500\n", encoding="utf-8")
            report = jev_pairing_performance.build_report(history, results)

        self.assertEqual(report["arms"]["codex_raw"]["graded_races"], 2)  # v1 も採点に残る
        raw = report["playbook_effect"]["codex"]["raw"]
        self.assertEqual(raw["diff"]["n"], 1)
        self.assertEqual(raw["diff"]["mean_diff_yen"], 1000.0)  # 900 − (−100)
        self.assertIsNone(raw["diff"]["ci95"])  # 30件未満は区間を出さない
        self.assertEqual(raw["verdict"], "accruing")
        self.assertEqual(report["playbook_effect"]["claude"]["jev"]["diff"]["n"], 0)


class SharedStatsTest(unittest.TestCase):
    def test_build_overview_uses_shared_stats(self) -> None:
        import build_overview

        self.assertIs(build_overview.paired_bootstrap, paired_stats.paired_bootstrap)
        self.assertIs(build_overview.verdict, paired_stats.verdict)

    def test_verdict_needs_500_and_interval(self) -> None:
        self.assertEqual(paired_stats.verdict({"n": 499, "ci95": [10, 20]}), "accruing")
        self.assertEqual(paired_stats.verdict({"n": 500, "ci95": [10, 20]}), "playbook_better")
        self.assertEqual(paired_stats.verdict({"n": 500, "ci95": [-20, -10]}), "baseline_better")
        self.assertEqual(paired_stats.verdict({"n": 500, "ci95": [-10, 10]}), "no_difference")


class MorningBatchTest(unittest.TestCase):
    def test_jev_runs_again_after_playbook_predictions(self) -> None:
        text = (ROOT / "run_morning.bat").read_text(encoding="utf-8")
        self.assertLess(text.index("python playbook_predict.py"), text.rindex("python jev_shadow.py"))


if __name__ == "__main__":
    unittest.main()
