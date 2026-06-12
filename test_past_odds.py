"""過去日の3連単オッズが取得可能か検証する単発テスト。

戸田 1R を 3つの時期で試して、取得行数と非ゼロオッズ件数を出力する。
- 2025-12-01 (5ヶ月前)
- 2025-06-01 (1年前)
- 2024-12-15 (1年5ヶ月前: 学習データ範囲の最古近辺)
"""
import sys
import io

# Windows cmd の cp932 対策
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collect_race_data import scrape_odds_3t

TEST_CASES = [
    ("20251201", "02", 1, "5ヶ月前"),
    ("20250601", "02", 1, "1年前"),
    ("20241215", "02", 1, "1年5ヶ月前"),
]

print("=== 過去オッズ取得テスト ===\n")

for date_str, jcd, rno, label in TEST_CASES:
    print(f"--- {label}: {date_str} 戸田(jcd={jcd}) R{rno} ---")
    rows = scrape_odds_3t(jcd, rno, date_str)
    if not rows:
        print(f"  [FAIL] 0行 (取得不可)\n")
        continue
    n_total = len(rows)
    n_nonzero = sum(1 for r in rows if r[5] > 0.0)
    odds_values = [r[5] for r in rows if r[5] > 0.0]
    sample = rows[:3]
    print(f"  [OK] {n_total}行取得 / 非ゼロ {n_nonzero}件")
    if odds_values:
        print(f"  オッズ範囲: {min(odds_values):.1f} 〜 {max(odds_values):.1f}")
    print(f"  サンプル(先頭3行):")
    for r in sample:
        print(f"    {r[0]} {r[4]}: {r[5]}")
    print()

print("=== テスト完了 ===")
