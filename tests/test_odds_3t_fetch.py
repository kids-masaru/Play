"""3連単オッズの取り方（requests 1回、取れない時だけブラウザ）を確認する。ネットにはつながない。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import collect_race_data as c  # noqa: E402


def odds_html(values: list[str]) -> str:
    """本物のページと同じく、表の上から順に td.oddsPoint が並ぶHTML。"""
    rows = "".join(
        "<tr>" + "".join(f'<td class="oddsPoint">{v}</td>' for v in values[i:i + 6]) + "</tr>"
        for i in range(0, len(values), 6)
    )
    return f"<html><body><table>{rows}</table></body></html>"


class Odds3tFetchTest(unittest.TestCase):
    def setUp(self) -> None:
        # 120マス：1行目が 1-2-3,2-1-3,3-1-2,4-1-2,5-1-2,6-1-2 の順
        self.values = [f"{i + 1}.0" for i in range(120)]
        self.values[7] = "欠場"

    def test_reads_all_120_combinations_in_table_order(self) -> None:
        with patch.object(c, "fetch_url", return_value=odds_html(self.values)) as fetch, \
             patch.object(c, "_scrape_odds_3t_browser") as browser:
            rows = c.scrape_odds_3t("01", 3, "20261019")
        browser.assert_not_called()  # 1回で取れたらブラウザは開かない
        fetch.assert_called_once()
        self.assertIn("odds3t?rno=3&jcd=01&hd=20261019", fetch.call_args.args[0])
        self.assertEqual(len(rows), 120)
        self.assertEqual(rows[0], ["20261019_桐生_3", "2026-10-19", "桐生", 3, "1-2-3", 1.0])
        self.assertEqual(rows[1][4:], ["2-1-3", 2.0])
        self.assertEqual(rows[5][4:], ["6-1-2", 6.0])
        self.assertEqual(rows[6][4:], ["1-2-4", 7.0])
        self.assertEqual(rows[7][4:], ["2-1-4", 0.0])  # 数字でないものは 0.0（今までと同じ）
        self.assertEqual(rows[-1][4:], ["6-5-4", 120.0])
        self.assertEqual(len({r[4] for r in rows}), 120)

    def test_falls_back_to_browser_only_when_html_has_no_odds(self) -> None:
        for html in (None, "<html><body>発売前</body></html>"):
            with patch.object(c, "fetch_url", return_value=html), \
                 patch.object(c, "_scrape_odds_3t_browser", return_value=[["x"]]) as browser:
                self.assertEqual(c.scrape_odds_3t("24", 12, "20261019"), [["x"]])
            browser.assert_called_once()
            self.assertEqual(browser.call_args.args[1:], ("20261019_大村_12", "2026-10-19", "大村", 12))

    def test_browser_fallback_skips_images_and_other_sites(self) -> None:
        class Req:
            def __init__(self, url, kind):
                self.url, self.resource_type = url, kind

        class Route:
            def __init__(self, url, kind):
                self.request, self.result = Req(url, kind), None

            def abort(self):
                self.result = "abort"

            def continue_(self):
                self.result = "continue"

        cases = {
            ("https://www.boatrace.jp/owpc/pc/race/odds3t?rno=1", "document"): "continue",
            ("https://www.boatrace.jp/static_extra/pc/js/x.js", "script"): "continue",
            ("https://www.boatrace.jp/static_extra/pc/images/a.png", "image"): "abort",
            ("https://www.boatrace.jp/static_extra/pc/css/a.css", "stylesheet"): "abort",
            ("https://www.googletagmanager.com/gtm.js", "script"): "abort",
        }
        for (url, kind), expected in cases.items():
            route = Route(url, kind)
            c._block_unneeded_requests(route)
            self.assertEqual(route.result, expected, url)


if __name__ == "__main__":
    unittest.main()
