"""心得集の土台（保存・差分検証・時系列ガード・日付版・注入）を確認する。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import playbook as pb  # noqa: E402


def _apply(playbook, ops, target="2026-10-16", last="2026-10-15"):
    return pb.apply_ops(
        playbook, ops, target_date=target, result_last_date=last, reflector="claude"
    )


class ChronologyGuardTest(unittest.TestCase):
    def test_results_before_target_return_last_date(self) -> None:
        last = pb.guard_chronology("2026-10-16", ["2026-10-14", "2026-10-15", "2026-10-01"])
        self.assertEqual(last, "2026-10-15")

    def test_result_on_target_date_is_rejected(self) -> None:
        # 境界：対象日当日の結果は未来情報として拒否する
        with self.assertRaises(pb.FutureLeakError):
            pb.guard_chronology("2026-10-16", ["2026-10-15", "2026-10-16"])

    def test_result_after_target_date_is_rejected(self) -> None:
        with self.assertRaises(pb.FutureLeakError):
            pb.guard_chronology("2026-10-16", ["2026-10-17"])

    def test_no_results_returns_none(self) -> None:
        self.assertIsNone(pb.guard_chronology("2026-10-16", []))

    def test_bad_date_format_is_rejected(self) -> None:
        with self.assertRaises(pb.PlaybookError):
            pb.guard_chronology("2026/10/16", [])

    def test_apply_ops_rejects_whole_batch_on_future_result(self) -> None:
        book = pb.empty_playbook("codex")
        with self.assertRaises(pb.FutureLeakError):
            _apply(book, [{"op": "add", "text": "心得"}], last="2026-10-16")


class ApplyOpsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.book = pb.empty_playbook("codex")

    def test_add_assigns_sequential_ids_and_does_not_mutate_input(self) -> None:
        result = _apply(
            self.book,
            [
                {"op": "add", "text": "向かい風5m以上ではまくり差しを重視", "evidence_race_ids": ["r1", "r1"]},
                {"op": "add", "text": "1号艇B2級は頭から外す"},
            ],
        )
        items = result["playbook"]["items"]
        self.assertEqual([i["id"] for i in items], ["codex-001", "codex-002"])
        self.assertEqual(items[0]["evidence_race_ids"], ["r1"])
        self.assertEqual(items[0]["created_at"], "2026-10-16")
        self.assertEqual(result["playbook"]["updated_for"], "2026-10-16")
        self.assertEqual(self.book["items"], [])  # 元は変わらない
        self.assertEqual(len(result["applied"]), 2)
        self.assertEqual(result["applied"][0]["result_last_date"], "2026-10-15")

    def test_more_than_five_ops_is_rejected_as_rewrite(self) -> None:
        ops = [{"op": "add", "text": f"心得{i}"} for i in range(6)]
        with self.assertRaises(pb.PlaybookError):
            _apply(self.book, ops)

    def test_non_list_ops_is_rejected(self) -> None:
        with self.assertRaises(pb.PlaybookError):
            _apply(self.book, {"op": "add", "text": "x"})

    def test_invalid_ops_are_rejected_individually(self) -> None:
        result = _apply(
            self.book,
            [
                {"op": "add", "text": "あ" * 201},  # 長すぎ
                {"op": "add", "text": "   "},  # 空
                {"op": "rewrite", "text": "全部"},  # 知らない操作
                {"op": "update", "id": "codex-999", "text": "x"},  # 存在しないID
                {"op": "add", "text": "あ" * 200},  # ちょうど200字は通る
            ],
        )
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 4)
        self.assertTrue(all(r["status"] == "rejected" for r in result["rejected"]))
        self.assertTrue(all(r["reject_reason"] for r in result["rejected"]))

    def test_update_and_disable(self) -> None:
        book = _apply(self.book, [{"op": "add", "text": "古い心得"}, {"op": "add", "text": "消す心得"}])["playbook"]
        result = _apply(
            book,
            [
                {"op": "update", "id": "codex-001", "text": "新しい心得"},
                {"op": "disable", "id": "codex-002", "reason": "3回続けて外れた"},
            ],
            target="2026-10-17",
            last="2026-10-16",
        )
        items = {i["id"]: i for i in result["playbook"]["items"]}
        self.assertEqual(items["codex-001"]["text"], "新しい心得")
        self.assertEqual(items["codex-001"]["created_at"], "2026-10-16")
        self.assertEqual(items["codex-001"]["updated_at"], "2026-10-17")
        self.assertEqual(result["applied"][0]["previous_text"], "古い心得")
        self.assertEqual(items["codex-002"]["status"], "disabled")
        self.assertEqual(items["codex-002"]["disabled_reason"], "3回続けて外れた")

    def test_disabled_item_cannot_be_updated_and_disable_needs_reason(self) -> None:
        book = _apply(self.book, [{"op": "add", "text": "心得"}])["playbook"]
        book = _apply(book, [{"op": "disable", "id": "codex-001", "reason": "不要"}])["playbook"]
        result = _apply(
            book,
            [
                {"op": "update", "id": "codex-001", "text": "復活"},
                {"op": "disable", "id": "codex-001"},
            ],
        )
        self.assertEqual(len(result["applied"]), 0)
        self.assertEqual(len(result["rejected"]), 2)

    def test_same_item_twice_in_one_day_is_rejected(self) -> None:
        book = _apply(self.book, [{"op": "add", "text": "心得"}])["playbook"]
        result = _apply(
            book,
            [
                {"op": "update", "id": "codex-001", "text": "修正1"},
                {"op": "disable", "id": "codex-001", "reason": "やっぱり不要"},
            ],
        )
        self.assertEqual(len(result["applied"]), 1)
        self.assertEqual(len(result["rejected"]), 1)

    def test_duplicate_text_is_rejected(self) -> None:
        book = _apply(self.book, [{"op": "add", "text": "同じ心得"}])["playbook"]
        result = _apply(book, [{"op": "add", "text": " 同じ心得 "}])
        self.assertEqual(len(result["rejected"]), 1)

    def test_active_item_limit(self) -> None:
        book = self.book
        for day in range(6):
            ops = [{"op": "add", "text": f"心得{day}-{i}"} for i in range(5)]
            book = _apply(book, ops)["playbook"]
        self.assertEqual(len(pb.active_items(book)), 30)
        result = _apply(book, [{"op": "add", "text": "31件目"}])
        self.assertEqual(len(result["rejected"]), 1)
        # 無効化すれば枠が空いて追加できる
        result = _apply(
            book,
            [{"op": "disable", "id": "codex-001", "reason": "古い"}, {"op": "add", "text": "31件目"}],
        )
        self.assertEqual(len(result["applied"]), 2)
        self.assertEqual(len(pb.active_items(result["playbook"])), 30)


class StorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_playbook_loads_empty(self) -> None:
        book = pb.load_playbook("claude", self.base)
        self.assertEqual(book["model_key"], "claude")
        self.assertEqual(book["items"], [])

    def test_unknown_model_is_rejected(self) -> None:
        with self.assertRaises(pb.PlaybookError):
            pb.load_playbook("gemini", self.base)

    def test_save_and_load_roundtrip(self) -> None:
        book = _apply(pb.empty_playbook("claude"), [{"op": "add", "text": "心得"}])["playbook"]
        pb.save_playbook(book, self.base)
        self.assertEqual(pb.load_playbook("claude", self.base), book)

    def test_broken_file_raises(self) -> None:
        (self.base / "claude.json").write_text("{壊れた", encoding="utf-8")
        with self.assertRaises(pb.PlaybookError):
            pb.load_playbook("claude", self.base)

    def test_model_mismatch_raises(self) -> None:
        pb.save_playbook(pb.empty_playbook("codex"), self.base)
        (self.base / "codex.json").rename(self.base / "claude.json")
        with self.assertRaises(pb.PlaybookError):
            pb.load_playbook("claude", self.base)

    def test_append_changes(self) -> None:
        result = _apply(pb.empty_playbook("codex"), [{"op": "add", "text": "心得"}, {"op": "x"}])
        count = pb.append_changes(result["applied"] + result["rejected"], self.base)
        self.assertEqual(count, 2)
        lines = (self.base / "changes.jsonl").read_text(encoding="utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
        self.assertEqual([r["status"] for r in rows], ["applied", "rejected"])
        self.assertTrue(all(r["recorded_at"] for r in rows))
        self.assertEqual(pb.append_changes([], self.base), 0)

    def test_snapshot_falls_back_to_previous_day_and_never_future(self) -> None:
        book1 = _apply(pb.empty_playbook("codex"), [{"op": "add", "text": "15日の心得"}], target="2026-10-15", last="2026-10-14")["playbook"]
        book2 = _apply(book1, [{"op": "add", "text": "17日の心得"}], target="2026-10-17", last="2026-10-16")["playbook"]
        info1 = pb.save_snapshot(book1, "2026-10-15", self.base)
        pb.save_snapshot(book2, "2026-10-17", self.base)

        # 16日は版が無いので15日の版を使う（17日の版は未来なので使わない）
        snap = pb.load_snapshot("codex", "2026-10-16", self.base)
        self.assertEqual(snap["snapshot_date"], "2026-10-15")
        self.assertEqual(snap["hash"], info1["hash"])
        self.assertEqual(snap["active_count"], 1)

        self.assertEqual(pb.load_snapshot("codex", "2026-10-17", self.base)["snapshot_date"], "2026-10-17")
        self.assertIsNone(pb.load_snapshot("codex", "2026-10-14", self.base))
        self.assertIsNone(pb.load_snapshot("claude", "2026-10-16", self.base))

    def test_broken_snapshot_is_skipped(self) -> None:
        book = _apply(pb.empty_playbook("codex"), [{"op": "add", "text": "心得"}], target="2026-10-14", last="2026-10-13")["playbook"]
        pb.save_snapshot(book, "2026-10-14", self.base)
        broken = pb.snapshot_path("codex", "2026-10-15", self.base)
        broken.write_text("{壊れた", encoding="utf-8")
        self.assertEqual(pb.load_snapshot("codex", "2026-10-15", self.base)["snapshot_date"], "2026-10-14")


class HashAndInjectionTest(unittest.TestCase):
    def _book(self):
        book = _apply(
            pb.empty_playbook("gemma_ft"),
            [{"op": "add", "text": "心得A"}, {"op": "add", "text": "心得B"}, {"op": "add", "text": "心得C"}],
        )["playbook"]
        return book

    def test_hash_ignores_stats_but_tracks_text(self) -> None:
        book = self._book()
        used = pb.record_usage(book, ["gemma_ft-001"], hit=True, profit=1200)
        self.assertEqual(pb.content_hash(book), pb.content_hash(used))
        edited = _apply(book, [{"op": "update", "id": "gemma_ft-001", "text": "心得A改"}])["playbook"]
        self.assertNotEqual(pb.content_hash(book), pb.content_hash(edited))

    def test_record_usage_ignores_unknown_and_duplicate_ids(self) -> None:
        book = pb.record_usage(self._book(), ["gemma_ft-002", "gemma_ft-002", "x-999"], hit=False, profit=-500)
        items = {i["id"]: i for i in book["items"]}
        self.assertEqual(items["gemma_ft-002"]["use_count"], 1)
        self.assertEqual(items["gemma_ft-002"]["use_hits"], 0)
        self.assertEqual(items["gemma_ft-002"]["use_profit"], -500)

    def test_injection_orders_by_profit_and_skips_disabled(self) -> None:
        book = self._book()
        book = pb.record_usage(book, ["gemma_ft-003"], hit=True, profit=2000)
        book = pb.record_usage(book, ["gemma_ft-001"], hit=False, profit=-500)
        book = _apply(book, [{"op": "disable", "id": "gemma_ft-002", "reason": "不要"}])["playbook"]
        inj = pb.build_injection(book)
        self.assertEqual(inj["item_ids"], ["gemma_ft-003", "gemma_ft-001"])
        self.assertEqual(inj["item_count"], 2)
        self.assertTrue(inj["text"].startswith(pb.INJECTION_HEADER))
        self.assertIn("- [gemma_ft-003] 心得C", inj["text"])
        self.assertNotIn("心得B", inj["text"])
        self.assertEqual(inj["hash"], pb.content_hash(book))

    def test_injection_respects_char_limit(self) -> None:
        book = pb.empty_playbook("gemma_ft")
        for day in range(2):
            ops = [{"op": "add", "text": f"{day}{i}" + "あ" * 190} for i in range(5)]
            book = _apply(book, ops)["playbook"]
        inj = pb.build_injection(book)  # ローカルモデルは1,500字まで
        self.assertLessEqual(len(inj["text"]), 1500)
        self.assertGreater(inj["item_count"], 0)
        self.assertLess(inj["item_count"], 10)
        self.assertEqual(pb.inject_char_limit("claude"), 4000)
        self.assertEqual(len(pb.build_injection(book, char_limit=4000)["item_ids"]), 10)

    def test_empty_playbook_injects_nothing(self) -> None:
        inj = pb.build_injection(pb.empty_playbook("claude"))
        self.assertEqual(inj["text"], "")
        self.assertEqual(inj["item_ids"], [])


if __name__ == "__main__":
    unittest.main()
