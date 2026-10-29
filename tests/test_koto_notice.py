"""KOTO 経由のお知らせ（koto_notice.py）と、3か所の送信が「KOTO→だめならLINE」になっていることを確認する。通信はしない。"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import koto_notice  # noqa: E402

# 試験用の値（実在しない）
ENV = {"KOTO_NOTICE_URL": "https://koto.example.test/api/owner-notice", "KOTO_NOTICE_KEY": "k" * 40}


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class KotoNoticeTest(unittest.TestCase):
    def test_notice_id_is_stable_and_valid(self):
        now = datetime(2026, 10, 23, 23, 0)
        a = koto_notice.notice_id_for("boatrace_daily", "日報", now)
        self.assertEqual(a, koto_notice.notice_id_for("boatrace_daily", "日報", now))
        self.assertNotEqual(a, koto_notice.notice_id_for("boatrace_daily", "日報2", now))
        self.assertRegex(a, r"^[A-Za-z0-9][A-Za-z0-9:._-]{7,79}$")  # KOTO 側の決まりと同じ形

    def test_sends_with_bearer_and_returns_true(self):
        calls = []

        def fake_post(url, json, headers, timeout):
            calls.append((url, json, headers, timeout))
            return FakeResponse(200)

        with patch.dict(os.environ, ENV), patch("requests.post", fake_post):
            self.assertTrue(koto_notice.send_via_koto("boatrace_daily", "日報"))
        url, body, headers, timeout = calls[0]
        self.assertEqual(url, ENV["KOTO_NOTICE_URL"])
        self.assertEqual(body["topic"], "boatrace_daily")
        self.assertNotIn("secret", body)  # 合言葉は本文に入れない
        self.assertEqual(headers["Authorization"], "Bearer " + ENV["KOTO_NOTICE_KEY"])
        self.assertEqual(timeout, koto_notice.TIMEOUT_SECONDS)

    def test_returns_false_without_settings_or_on_failure(self):
        with patch.dict(os.environ, {"KOTO_NOTICE_URL": "", "KOTO_NOTICE_KEY": ""}):
            self.assertFalse(koto_notice.send_via_koto("boatrace_daily", "日報"))
        with patch.dict(os.environ, {**ENV, "KOTO_NOTICE_URL": "http://insecure.example.test/x"}):
            self.assertFalse(koto_notice.send_via_koto("boatrace_daily", "日報"))
        with patch.dict(os.environ, ENV), patch("requests.post", lambda *a, **k: FakeResponse(502)):
            self.assertFalse(koto_notice.send_via_koto("boatrace_daily", "日報"))

        def boom(*args, **kwargs):
            raise ConnectionError("down")

        with patch.dict(os.environ, ENV), patch("requests.post", boom):
            self.assertFalse(koto_notice.send_via_koto("boatrace_daily", "日報"))


class RetryTest(unittest.TestCase):
    """返事が遅れたとき、同じ番号でもう1回だけ送る（LINEが2通届くのを防ぐ）。"""

    def test_timeout_then_success_uses_same_id(self):
        import requests

        bodies = []

        def flaky(url, json, headers, timeout):
            bodies.append(json)
            if len(bodies) == 1:
                raise requests.exceptions.Timeout()
            return FakeResponse(200)

        with patch.dict(os.environ, ENV), patch("requests.post", flaky):
            self.assertTrue(koto_notice.send_via_koto("boatrace_daily", "日報"))
        self.assertEqual(len(bodies), 2)
        self.assertEqual(bodies[0]["id"], bodies[1]["id"])

    def test_two_timeouts_give_up(self):
        import requests

        calls = []

        def slow(*args, **kwargs):
            calls.append(1)
            raise requests.exceptions.Timeout()

        with patch.dict(os.environ, ENV), patch("requests.post", slow):
            self.assertFalse(koto_notice.send_via_koto("boatrace_daily", "日報"))
        self.assertEqual(len(calls), 2)  # 3回以上は送らない

    def test_http_error_does_not_retry(self):
        calls = []

        def failing(*args, **kwargs):
            calls.append(1)
            return FakeResponse(502)

        with patch.dict(os.environ, ENV), patch("requests.post", failing):
            self.assertFalse(koto_notice.send_via_koto("boatrace_daily", "日報"))
        self.assertEqual(len(calls), 1)


class SenderWiringTest(unittest.TestCase):
    """3か所の送信が、まず KOTO を試してから LINE へ直接送る形になっていること。"""

    def test_three_senders_try_koto_first(self):
        for name, topic in (
            ("main_runner.py", "boatrace_daily"),
            ("morning_odds_runner.py", "boatrace_morning"),
            ("playbook_weekly_report.py", "boatrace_weekly"),
        ):
            source = (ROOT / name).read_text(encoding="utf-8")
            koto_at = source.find(f'send_via_koto("{topic}", message)')
            line_at = source.find("push_message(", koto_at if koto_at >= 0 else 0)
            self.assertGreaterEqual(koto_at, 0, name)
            self.assertGreater(line_at, koto_at, f"{name}: LINE直接送信がKOTOより前にある")

    def test_weekly_falls_back_to_line_when_koto_fails(self):
        import playbook_weekly_report as weekly

        with patch("koto_notice.send_via_koto", return_value=True), patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": ""}):
            self.assertTrue(weekly.send_line("見直し"))  # KOTO で届けば LINE は使わない
        with patch("koto_notice.send_via_koto", return_value=False), \
                patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "", "LINE_USER_ID": ""}):
            self.assertFalse(weekly.send_line("見直し"))  # KOTO がだめで LINE 設定も無ければ送らない

    def test_broken_helper_does_not_stop_the_batch(self):
        # KOTO部品が壊れていても例外で処理を止めない（LINEへ直接の流れに進む）
        import playbook_weekly_report as weekly

        def broken(*args, **kwargs):
            raise ImportError("koto_notice broken")

        with patch("koto_notice.send_via_koto", broken), \
                patch.dict(os.environ, {"LINE_CHANNEL_ACCESS_TOKEN": "", "LINE_USER_ID": ""}):
            self.assertFalse(weekly.send_line("見直し"))


if __name__ == "__main__":
    unittest.main()
