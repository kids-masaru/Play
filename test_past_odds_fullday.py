"""過去日(2025-06-01)の1日分フル取得テスト。

開催全会場×12レースを順次取得し、
- 成功率（取得行数 == 120 のレース割合）
- 1レース平均所要時間
- 全体所要時間
- 失敗レース一覧
を計測する。

結果は auto_research/wf_past_odds_test_20250601.csv に保存（後で再利用可能）。
"""
import os
import sys
import io
import time
import csv
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collect_race_data import get_venues_for_date, scrape_odds_3t, VENUE_MAP

TARGET_DATE = "20250601"
SLEEP_BETWEEN_RACES = 0.5  # 礼儀的スリープ（秒）
OUTPUT_CSV = os.path.join("auto_research", f"wf_past_odds_test_{TARGET_DATE}.csv")
LOG_FILE = os.path.join("logs", "past_odds_test.log")


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("auto_research", exist_ok=True)
    # ログファイル初期化
    open(LOG_FILE, "w", encoding="utf-8").close()

    t_overall_start = time.time()
    log(f"=== 過去オッズフル取得テスト: {TARGET_DATE} 開始 ===")

    venues = get_venues_for_date(TARGET_DATE)
    log(f"開催会場: {len(venues)} 場 = {venues}")
    if not venues:
        log("[FAIL] 開催会場ゼロ。テスト中止")
        return

    total_races = len(venues) * 12
    log(f"対象レース数: {total_races} ({len(venues)}場 × 12R)")

    all_rows = []
    success_races = 0
    failed_races = []
    race_durations = []

    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ID", "Date", "Venue", "R", "Combination", "Odds"])

        race_idx = 0
        for jcd in venues:
            venue_name = VENUE_MAP.get(jcd, f"V{jcd}")
            for rno in range(1, 13):
                race_idx += 1
                t_race_start = time.time()
                rows = scrape_odds_3t(jcd, rno, TARGET_DATE)
                t_elapsed = time.time() - t_race_start
                race_durations.append(t_elapsed)

                if len(rows) == 120 and sum(1 for r in rows if r[5] > 0) >= 100:
                    success_races += 1
                    writer.writerows(rows)
                    all_rows.extend(rows)
                    status = "OK"
                else:
                    failed_races.append((jcd, venue_name, rno, len(rows)))
                    status = f"FAIL(rows={len(rows)})"

                if race_idx % 10 == 0 or race_idx == total_races:
                    elapsed_total = time.time() - t_overall_start
                    eta = elapsed_total / race_idx * (total_races - race_idx)
                    log(
                        f"[{race_idx:3d}/{total_races}] {venue_name} R{rno} {status} "
                        f"({t_elapsed:.2f}s) | 経過 {elapsed_total/60:.1f}min ETA {eta/60:.1f}min"
                    )

                time.sleep(SLEEP_BETWEEN_RACES)

    t_overall = time.time() - t_overall_start
    avg_per_race = sum(race_durations) / len(race_durations) if race_durations else 0
    success_rate = success_races / total_races * 100 if total_races else 0

    log("")
    log("=== 集計 ===")
    log(f"全所要時間: {t_overall/60:.2f} 分")
    log(f"成功: {success_races}/{total_races} ({success_rate:.1f}%)")
    log(f"失敗: {len(failed_races)} レース")
    log(f"1レース平均: {avg_per_race:.2f}秒")
    log(f"取得行数合計: {len(all_rows)} 行")
    log(f"出力: {OUTPUT_CSV}")
    if failed_races:
        log("失敗詳細:")
        for jcd, vname, rno, nrows in failed_races[:20]:
            log(f"  - {vname}(jcd={jcd}) R{rno}: {nrows}行")
        if len(failed_races) > 20:
            log(f"  ... 他 {len(failed_races)-20} 件")

    # 1.5年分推計
    days_total = 365 + 5 * 30  # 約1年5ヶ月
    open_day_ratio = 0.95  # 開催日割合（平日のうち約95%は開催）
    races_per_day = total_races  # 仮にこの日と同じレース数で推計
    total_races_estimate = int(days_total * open_day_ratio * races_per_day)
    total_time_estimate_hours = total_races_estimate * avg_per_race / 3600
    log("")
    log("=== 1年5ヶ月分(全期間)の推計 ===")
    log(f"推定総レース数: {total_races_estimate:,} レース")
    log(f"推定総所要時間(順次): {total_time_estimate_hours:.1f} 時間")


if __name__ == "__main__":
    main()
