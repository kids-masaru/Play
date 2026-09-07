"""締切オッズ取得バッチ（CLV用）。

朝バッチ(morning_odds_runner.py)が前売りオッズを daily_odds_3t.csv に貯めるのに対し、
本スクリプトは「その日の全レース終了後（夜）」に同じ会場のオッズを再取得し、
締切（最終）オッズとして closing_odds_3t.csv に保存する。

朝オッズ vs 締切オッズ の2スナップショットが揃うことで、
compute_clv.py が CLV（Closing Line Value）を計算できるようになる。

想定運用: タスクスケジューラで毎晩 21:30 JST（全レース終了後）に実行。
  run_closing.bat から呼ぶ。

注意: 当日分を重複取得しても、同日の既存行を消してから書き直すので二重計上しない。
"""
import os
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from collect_race_data import (
    get_venues_for_date,
    scrape_odds_3t,
    close_odds_browser,
    append_to_csv,
    VENUE_MAP,
    ODDS_3T_HEADERS,
)

HERE = os.path.dirname(os.path.abspath(__file__))
CLOSING_FILE = os.path.join(HERE, "daily_data", "closing_odds_3t.csv")


def remove_existing_date(date_csv):
    """既存 closing_odds_3t.csv から対象日の行を除去（重複取得時の二重計上防止）。"""
    if not os.path.exists(CLOSING_FILE):
        return
    try:
        df = pd.read_csv(CLOSING_FILE, dtype=str)
    except Exception:
        return
    before = len(df)
    df = df[df["Date"].astype(str) != date_csv]
    if len(df) != before:
        df.to_csv(CLOSING_FILE, index=False)
        print(f"  > 既存の {date_csv} 分 {before - len(df)} 行を除去（再取得のため）")


def fetch_closing_odds(target_date_str):
    """対象日の締切オッズを全会場・全レース分取得して closing_odds_3t.csv に保存。"""
    target_date_csv = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:]}"
    print(f"--- 締切オッズ取得 ({target_date_csv}) ---")

    venues = get_venues_for_date(target_date_str)
    if not venues:
        print(f"  > {target_date_str} の開催会場はありません。")
        return False

    remove_existing_date(target_date_csv)

    print(f"  > 開催会場({len(venues)}): {venues}")
    total_rows = 0
    for jcd in venues:
        v_name = VENUE_MAP.get(jcd, jcd)
        print(f"    - 会場 {v_name} ({jcd})... ", end="", flush=True)
        venue_rows = []
        for rno in range(1, 13):
            time.sleep(0.3)
            o_rows = scrape_odds_3t(jcd, rno, target_date_str)
            if o_rows:
                venue_rows.extend(o_rows)
        if venue_rows:
            append_to_csv(CLOSING_FILE, ODDS_3T_HEADERS, venue_rows)
            total_rows += len(venue_rows)
        print(f"完了 ({len(venue_rows)}行)")

    print(f"  > 合計 {total_rows} 件の締切オッズを保存しました。")
    return total_rows > 0


def main():
    print("=== 締切オッズ取得バッチ 開始 ===")
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    target_date_str = now_jst.strftime("%Y%m%d")
    print(f"対象日: {now_jst.strftime('%Y-%m-%d')} (JST {now_jst.strftime('%H:%M')})")
    try:
        fetch_closing_odds(target_date_str)
    except Exception as e:
        print(f"[FATAL ERROR]\n{traceback.format_exc()}")
    finally:
        close_odds_browser()
    print("=== 締切オッズ取得バッチ 完了 ===")


if __name__ == "__main__":
    main()
