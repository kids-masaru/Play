"""バッチどうしが重ならない仕組み（batch_lock.py）と、各 .bat への組み込みを確認する。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import batch_lock as bl  # noqa: E402


class BatchLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.lock_dir = Path(self.tmp.name) / "locks"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _put(self, name: str, **fields) -> None:
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        lock = {"name": name, "pid": os.getpid(), "process_created": None,
                "started_at": datetime.now().isoformat(timespec="seconds"), **fields}
        bl.lock_path(name, self.lock_dir).write_text(json.dumps(lock), encoding="utf-8")

    def test_start_and_end_create_and_remove_the_mark(self) -> None:
        self.assertEqual(bl.main(["start", "daily", "--lock-dir", str(self.lock_dir)]), 0)
        lock = bl.read_lock("daily", self.lock_dir)
        self.assertTrue(bl.is_alive(lock))  # 持ち主（このテストの親プロセス）は動いている
        self.assertEqual(bl.main(["end", "daily", "--lock-dir", str(self.lock_dir)]), 0)
        self.assertIsNone(bl.read_lock("daily", self.lock_dir))
        # 2回目の end も失敗しない
        self.assertEqual(bl.main(["end", "daily", "--lock-dir", str(self.lock_dir)]), 0)

    def test_dead_process_old_or_broken_marks_are_ignored(self) -> None:
        self._put("closing", pid=999999999)
        self.assertEqual(bl.running_others(["closing"], self.lock_dir), [])
        old = (datetime.now() - timedelta(hours=bl.STALE_HOURS + 1)).isoformat(timespec="seconds")
        self._put("morning", started_at=old)
        self.assertEqual(bl.running_others(["morning"], self.lock_dir), [])
        self.lock_dir.joinpath("daily.lock").write_text("壊れた中身", encoding="utf-8")
        self.assertEqual(bl.running_others(["daily"], self.lock_dir), [])
        # PID が使い回された場合（起動時刻が違う）も動いていない扱い
        self._put("toto", process_created=1.0)
        self.assertEqual(bl.running_others(["toto"], self.lock_dir), [])

    def test_waits_until_other_batch_finishes(self) -> None:
        self._put("closing")
        calls = []

        def fake_sleep(seconds):
            calls.append(seconds)
            bl.remove_lock("closing", self.lock_dir)  # 待っている間に締切バッチが終わる

        result = bl.wait_for(["closing", "morning"], self.lock_dir, max_wait_minutes=180, sleep=fake_sleep)
        self.assertFalse(result["timed_out"])
        self.assertEqual(len(calls), 1)

    def test_gives_up_waiting_after_the_limit(self) -> None:
        self._put("daily")
        clock = iter([0.0, 0.0, 600.0, 600.0])
        with patch.object(bl.time, "monotonic", side_effect=lambda: next(clock)):
            result = bl.wait_for(["daily"], self.lock_dir, max_wait_minutes=5, sleep=lambda s: None)
        self.assertTrue(result["timed_out"])
        self.assertEqual(result["still_running"], ["daily"])

    def test_failure_never_stops_the_batch(self) -> None:
        with patch.object(bl, "write_lock", side_effect=OSError("書けない")):
            self.assertEqual(bl.main(["start", "daily", "--lock-dir", str(self.lock_dir)]), 0)


class WiringTest(unittest.TestCase):
    def _bat(self, name: str) -> str:
        return (ROOT / name).read_text(encoding="utf-8")

    def test_daily_waits_and_logs_main_runner(self) -> None:
        bat = self._bat("run_daily.bat")
        start = bat.index("python batch_lock.py start daily --wait-for closing morning")
        runner = bat.index("python main_runner.py >> \"%~dp0logs\\daily.log\" 2>&1")
        self.assertLess(start, runner)
        self.assertLess(bat.index("set PYTHONIOENCODING=utf-8"), runner)
        self.assertLess(bat.index("python playbook_reflect.py"), bat.index("python batch_lock.py end daily"))

    def test_morning_waits_for_daily_and_releases_at_the_end(self) -> None:
        bat = self._bat("run_morning.bat")
        self.assertLess(bat.index("python batch_lock.py start morning --wait-for daily"),
                        bat.index("python playbook_weekly_report.py"))
        self.assertLess(bat.index("python jev_shadow.py"), bat.index("python batch_lock.py end morning"))

    def test_closing_marks_itself_without_waiting(self) -> None:
        bat = self._bat("run_closing.bat")
        self.assertIn("python batch_lock.py start closing >>", bat)
        self.assertNotIn("start closing --wait-for", bat)
        self.assertLess(bat.index("python compute_clv.py"), bat.index("python batch_lock.py end closing"))


if __name__ == "__main__":
    unittest.main()
