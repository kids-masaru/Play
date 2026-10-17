"""toto の答え合わせ修正（公式結果の読み分け・全試合の答え合わせ・チーム名・指示文）を確認する。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "toto"))

import fetch_toto_results as ftr  # noqa: E402
import settle_results as sr  # noqa: E402
from predict_gemini import normalize_team  # noqa: E402


def _result_table(picks: list[str]) -> str:
    rows = "".join(
        f"<tr><td>10/09</td><td>会場</td><td>{i + 1}</td><td>ホーム{i}</td><td>1-0</td><td>アウェイ{i}</td><td>{p}</td></tr>"
        for i, p in enumerate(picks)
    )
    return (
        "<table><tr><th>開催日</th><th>競技場</th><th>No</th><th>ホーム</th><th>試合結果</th>"
        f"<th>アウェイ</th><th>くじ結果</th></tr>{rows}</table>"
    )


def _payout_table(round_no: int, amount: str) -> str:
    return (
        f"<table><tr><th>第{round_no}回</th><th>1等</th></tr>"
        f"<tr><td>当せん金</td><td>{amount}円</td></tr><tr><td>当せん口数</td><td>10口</td></tr></table>"
    )


def _goal3_table() -> str:
    rows = "".join(f"<tr><td>10/09</td><td>会場</td><td>{i}</td><td>チーム</td><td>1</td><td>{g}</td></tr>" for i, g in enumerate("103021"))
    return f"<table><tr><th>開催日</th><th>競技場</th><th>No</th><th>予想チーム</th><th>得点</th><th>くじ結果</th></tr>{rows}</table>"


class OfficialResultParseTest(unittest.TestCase):
    def test_weekday_mini_round_and_goal3_is_not_read_as_result(self) -> None:
        html = (
            "<h2>第1651回 mini toto-A組　くじ結果</h2>"
            + _result_table(["2", "0", "2", "1", "2"]) + _payout_table(1651, "9,040")
            + "<h2>第1651回 totoGOAL3　くじ結果</h2>"
            + _goal3_table() + _payout_table(1651, "53,480")
        )
        parsed = ftr.parse_round(1651, html, [("mini_a", 5)])
        self.assertEqual(parsed["results"], {"mini_a": ["A", "D", "A", "H", "A"]})
        self.assertEqual(parsed["mini_a"], 9040)
        self.assertEqual(parsed["goal3"], 53480)  # 当せん金は残すが、結果（得点数）は勝敗として読まない
        self.assertNotIn("goal3", parsed["results"])
        self.assertTrue(ftr.is_complete(parsed, [("mini_a", 5)]))

    def test_full_round_assigns_tables_by_match_count(self) -> None:
        toto = list("1012222211221")
        html = (
            "<h2>第1660回 toto　くじ結果</h2>"
            + _result_table(toto) + _payout_table(1660, "16,743,700")
            + _result_table(list("01102")) + _payout_table(1660, "22,680")
            + _result_table(list("22211")) + _payout_table(1660, "7,040")
            + _goal3_table() + _payout_table(1660, "262,010")
        )
        expected = [("toto", 13), ("mini_a", 5), ("mini_b", 5)]
        parsed = ftr.parse_round(1660, html, expected)
        self.assertEqual(len(parsed["results"]["toto"]), 13)
        self.assertEqual(parsed["results"]["mini_a"], ["D", "H", "H", "D", "A"])
        self.assertEqual(parsed["results"]["mini_b"], ["A", "A", "A", "H", "H"])
        self.assertEqual((parsed["toto"], parsed["mini_a"], parsed["mini_b"], parsed["goal3"]), (16743700, 22680, 7040, 262010))
        self.assertTrue(ftr.is_complete(parsed, expected))

    def test_unpublished_page_and_old_version(self) -> None:
        self.assertIsNone(ftr.parse_round(1700, "<h2>第1699回 toto　くじ結果</h2>", [("toto", 13)]))
        old = {"results": {"toto": ["H"] * 13}}  # 版なし＝修正前の読み方
        self.assertFalse(ftr.is_complete(old, [("toto", 13)]))

    def test_expected_kuji_skips_goal3(self) -> None:
        round_data = {"kuji": {"goal3": {"matches": [{}] * 3}, "mini_a": {"matches": [{}] * 5}}}
        self.assertEqual(ftr.expected_kuji(round_data), [("mini_a", 5)])


class SettleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name)
        matches = [{"no": str(i + 1), "date": "2026-10-10", "home": f"H{i}", "away": f"A{i}"} for i in range(3)]
        mini_only = {"no": "5", "date": "2026-10-11", "home": "MH", "away": "MA"}
        round_data = {
            "round": 1660,
            "kuji": {
                "toto": {"matches": matches},
                "mini_a": {"matches": [matches[1], mini_only]},
                "goal3": {"matches": [matches[0]]},
            },
        }
        (self.data_dir / "round_1660.json").write_text(json.dumps(round_data, ensure_ascii=False), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_kuji_matches_are_settled_with_official_first(self) -> None:
        official = {"1660": {"version": 2, "results": {"toto": ["H", "D", ""], "mini_a": ["D", "A"]}}}
        lut = {("2026-10-10", "H2", "A2"): "A", ("2026-10-10", "H0", "A0"): "A"}  # H0はJリーグ側と食い違い
        with patch.object(sr, "DATA_DIR", str(self.data_dir)):
            out = sr.settle_round(1660, lut, {"H0", "A0", "H2", "A2"}, lambda name, teams: name, date(2026, 10, 17), {}, official)
        by_id = {r["match_id"]: r for r in out["results"]}
        self.assertEqual(out["n_matches"], 4)  # toto 3試合 + mini だけの1試合（重複は1つに）
        self.assertEqual(by_id["1660-1"]["actual"], "H")  # 公式結果を優先
        self.assertEqual(by_id["1660-2"]["actual"], "D")
        self.assertEqual(by_id["1660-3"]["actual"], "A")  # 公式に無い分はJリーグ結果
        self.assertEqual(by_id["1660-mini_a-5"]["actual"], "A")  # miniだけの試合も答え合わせ
        self.assertEqual(out["n_settled"], 4)

    def test_old_official_version_is_ignored(self) -> None:
        path = self.data_dir / "official_results.json"
        path.write_text(json.dumps({"1660": {"results": {"toto": ["H"]}}, "1661": {"version": 2, "results": {}}}), encoding="utf-8")
        with patch.object(sr, "DATA_DIR", str(self.data_dir)):
            self.assertEqual(list(sr.load_official()), ["1661"])


class TeamAndPromptTest(unittest.TestCase):
    def test_tokyo_verdy_alias(self) -> None:
        self.assertEqual(normalize_team("東京ヴェルディ", ["東京Ｖ", "FC東京"]), "東京Ｖ")
        self.assertEqual(normalize_team("FC東京", ["東京Ｖ", "FC東京"]), "FC東京")

    def test_prompts_do_not_force_a_mix(self) -> None:
        import predict_claude
        import predict_codex

        for module in (predict_codex, predict_claude):
            prompt = module.build_prompt([{"match_key": "k"}], {"settled_predictions": 0})
            self.assertNotIn("realistic mix", prompt)
            self.assertIn("Choose the single most likely outcome", prompt)
            self.assertIn("always pick H", prompt)


if __name__ == "__main__":
    unittest.main()
