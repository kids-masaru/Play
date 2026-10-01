"""Jevシャドー判定の入力契約・未来情報防止・障害分離を確認する。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import jev_shadow  # noqa: E402
import update_battle_dashboard  # noqa: E402


class JevShadowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.race = {
            "race_id": "20260930_平和島_5",
            "date": "2026-09-30",
            "venue": "平和島",
            "r": 5,
            "weather": "晴",
            "wind_speed": "2m",
            "wind_dir": "向かい風",
            "wave": "2cm",
            "water_temp": "24℃",
            "boats": [
                {
                    "lane": lane,
                    "name": f"選手{lane}",
                    "rank": "A1" if lane == 1 else "B1",
                    "win_rate": 6.5 if lane == 1 else 4.5,
                    "motor_no": str(10 + lane),
                    "weight": 52.0,
                    "tilt": 0.0,
                    "ex_time": 6.7,
                }
                for lane in range(1, 7)
            ],
            "odds_top": [
                {"combo": "1-2-3", "odds": 8.4},
                {"combo": "1-3-2", "odds": 10.2},
            ],
            "ai_picks_grok": "1-2-3:100, 1-3-2:100",
            "ai_picks_codex": "1-2-3:100, 2-1-3:100",
            "ai_log_grok": "この長い説得的文章はJevへ渡してはいけない",
            "ai_log_codex": "結果を誘導する自由記述",
        }
        self.performance = {
            "latest_result_date": "2026-09-29",
            "periods": {
                "weekly": {
                    "models": [
                        {"key": "stakes_grok", "n": 100, "roi": 90.0},
                        {"key": "stakes_codex", "n": 100, "roi": 95.0},
                    ]
                },
                "monthly": {
                    "models": [
                        {"key": "stakes_grok", "n": 300, "roi": 88.0},
                        {"key": "stakes_codex", "n": 300, "roi": 91.0},
                    ]
                },
            },
        }

    def test_parse_stakes_normalizes_and_rejects_duplicate_lanes(self) -> None:
        result = jev_shadow.parse_stakes("1-2-3:100, 1ー3ー2：200, 1-1-2:500")
        self.assertEqual(
            result,
            [
                {"combo": "1-2-3", "stake_yen": 100},
                {"combo": "1-3-2", "stake_yen": 200},
            ],
        )

    def test_state_is_structured_and_excludes_free_form_logs(self) -> None:
        state = jev_shadow.build_race_state(self.race, self.performance, {})
        serialized = json.dumps(state, ensure_ascii=False)

        self.assertEqual(state["agreement"]["active_model_count"], 2)
        self.assertEqual(state["candidates"][0]["combo"], "1-2-3")
        self.assertEqual(state["candidates"][0]["model_count"], 2)
        self.assertNotIn("説得的文章", serialized)
        self.assertNotIn("結果を誘導", serialized)
        self.assertNotIn("選手1", serialized)

    def test_questions_keep_action_and_candidate_separate(self) -> None:
        state = jev_shadow.build_race_state(self.race, self.performance, {})
        questions, candidate_map = jev_shadow.build_questions(state)

        self.assertEqual(questions["action"]["type"], "choice")
        self.assertEqual(questions["data_sufficient"]["type"], "noul")
        self.assertEqual(questions["evidence_strength"]["type"], "score")
        self.assertEqual(candidate_map["candidate_1_2_3"], "1-2-3")

    def test_single_source_state_contains_only_requested_model(self) -> None:
        state = jev_shadow.build_race_state(
            self.race,
            self.performance,
            {},
            source_ids=("codex",),
        )

        self.assertEqual(state["agreement"]["active_model_count"], 1)
        self.assertEqual(
            [model["model_id"] for model in state["model_predictions"]],
            ["codex"],
        )

    def test_selector_only_questions_do_not_mix_purchase_action(self) -> None:
        state = jev_shadow.build_race_state(
            self.race,
            self.performance,
            {},
            source_ids=("claude",),
        )

        questions, _ = jev_shadow.build_questions(state, selector_only=True)

        self.assertNotIn("action", questions)
        self.assertIn("candidate", questions)
        self.assertIn("source-model history", questions["data_sufficient"]["instructions"])

    def test_temporal_boundary_rejects_same_day_results(self) -> None:
        with self.assertRaisesRegex(ValueError, "未来情報防止"):
            jev_shadow.validate_temporal_boundary(
                "2026-09-30", {"latest_result_date": "2026-09-30"}
            )

    def test_experiment_temporal_boundary_rejects_same_day_results(self) -> None:
        with self.assertRaisesRegex(ValueError, "Jev比較成績"):
            jev_shadow.validate_experiment_temporal_boundary(
                "2026-09-30", {"latest_result_date": "2026-09-30"}
            )

    def test_history_keeps_pairing_arms_separate(self) -> None:
        base = {
            "date": "2026-09-30",
            "race_id": "r1",
            "strategy_version": jev_shadow.STRATEGY_VERSION,
            "experiment_version": jev_shadow.EXPERIMENT_VERSION,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.jsonl"
            jev_shadow.append_history(
                path, {**base, "experiment_id": "codex_jev"}
            )
            jev_shadow.append_history(
                path, {**base, "experiment_id": "claude_jev"}
            )

            history = jev_shadow.load_history(path)

        self.assertEqual(len(history), 2)

    def test_api_connection_failure_has_clear_error(self) -> None:
        api_key = "dummy-key-not-logged"
        with patch.object(jev_shadow, "urlopen", side_effect=URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Jev API接続失敗") as caught:
                jev_shadow.call_jev(
                    {"race": {"race_id": "test"}},
                    {"action": {"type": "noul", "instructions": "test"}},
                    api_key,
                )
        self.assertNotIn(api_key, str(caught.exception))

    def test_load_api_key_uses_process_environment(self) -> None:
        with patch.dict(os.environ, {"TYPESAFE_API_KEY": "test-key"}, clear=False):
            self.assertEqual(jev_shadow.load_api_key(), "test-key")

    def test_orchestration_continues_when_jev_fails(self) -> None:
        calls = []

        def fake_run(script, allow_fail=False, extra_args=None):
            calls.append((script, allow_fail, extra_args))
            return script != "jev_shadow.py"

        argv = [
            "update_battle_dashboard.py",
            "--no-push",
            "--skip-gemini",
            "--skip-grok",
            "--skip-codex",
            "--skip-claude",
            "--skip-gemma",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(update_battle_dashboard, "copy_sources"),
            patch.object(update_battle_dashboard, "run_py", side_effect=fake_run),
            patch.object(update_battle_dashboard, "publish") as publish,
        ):
            update_battle_dashboard.main()

        self.assertIn(("jev_shadow.py", True, None), calls)
        self.assertIn(("jev_pairing_performance.py", True, None), calls)
        self.assertLess(
            [item[0] for item in calls].index("model_performance.py"),
            [item[0] for item in calls].index("jev_shadow.py"),
        )
        self.assertLess(
            [item[0] for item in calls].index("jev_shadow.py"),
            [item[0] for item in calls].index("jev_pairing_performance.py"),
        )
        publish.assert_called_once_with(no_push=True)

    def test_orchestration_can_disable_jev(self) -> None:
        calls = []

        def fake_run(script, allow_fail=False, extra_args=None):
            calls.append(script)
            return True

        argv = [
            "update_battle_dashboard.py",
            "--no-push",
            "--skip-gemini",
            "--skip-grok",
            "--skip-codex",
            "--skip-claude",
            "--skip-gemma",
            "--skip-jev",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(update_battle_dashboard, "copy_sources"),
            patch.object(update_battle_dashboard, "run_py", side_effect=fake_run),
            patch.object(update_battle_dashboard, "publish"),
        ):
            update_battle_dashboard.main()

        self.assertNotIn("jev_shadow.py", calls)
        self.assertIn("jev_pairing_performance.py", calls)

    def test_private_jev_histories_are_not_publish_targets(self) -> None:
        private_names = {
            "dashboard/public/daily_data/jev_shadow_history.jsonl",
            "dashboard/public/daily_data/jev_backtest_decisions.jsonl",
            "dashboard/public/daily_data/jev_backtest_git_decisions.jsonl",
        }

        self.assertTrue(private_names.isdisjoint(update_battle_dashboard.PUBLISH_FILES))
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in private_names:
            self.assertIn(name, ignore_text)


if __name__ == "__main__":
    unittest.main()
