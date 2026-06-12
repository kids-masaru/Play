"""past_odds 全期間取得の欠損実態を分析する。

各日のCSV行数とログを突き合わせて、
- 欠損レース数別の分布（0/1-5/6-20/21-50/51+）
- 重大欠損日 (>=10レース失敗) のリスト
- 朝バッチ時間帯と被った日の特定
を出力する。
"""
import os
import re
import csv
from collections import defaultdict
from datetime import datetime

BACKFILL_DIR = os.path.join("past_data", "past_odds_3t_backfill")
LOG_FILE = os.path.join("logs", "backfill_odds.log")
NO_RACE_FILE = os.path.join(BACKFILL_DIR, "no_race.txt")

# ログをパースして (date, failed_count, total_races, time) を抽出
# 例: "[ 290/545] 20250916 PARTIAL(79..." races=77/13場
LINE_RE = re.compile(
    r"\[\s*(\d+)/(\d+)\]\s+(\d{8})\s+(OK|PARTIAL\((\d+)\D|NO_RACE)"
    r"(?:.*?races=(\d+)/(\d+))?"
)


def load_no_race():
    if not os.path.exists(NO_RACE_FILE):
        return set()
    with open(NO_RACE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def parse_log():
    """ログから日付ごとの (status, failed_count, success_races, total_venues) を抽出。"""
    records = {}
    with open(LOG_FILE, "rb") as f:
        raw = f.read()
    # 文字化けしている部分があるが、ASCII (数字・英字) は読めるはずなのでバイト→str (lossy)
    text = raw.decode("utf-8", errors="replace")

    for line in text.split("\n"):
        m = LINE_RE.search(line)
        if not m:
            continue
        date_str = m.group(3)
        status_raw = m.group(4)
        failed = m.group(5)
        succ_races = m.group(6)
        total_venues = m.group(7)

        if status_raw == "OK":
            status = "OK"
            failed_n = 0
        elif status_raw.startswith("PARTIAL"):
            status = "PARTIAL"
            failed_n = int(failed) if failed else 0
        else:
            status = "NO_RACE"
            failed_n = 0

        records[date_str] = {
            "status": status,
            "failed": failed_n,
            "success_races": int(succ_races) if succ_races else 0,
            "total_venues": int(total_venues) if total_venues else 0,
        }
    return records


def parse_log_time(date_str):
    """ログから特定日付の処理時刻を抜き出す（朝バッチ被り判定用）。"""
    with open(LOG_FILE, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    pattern = re.compile(rf"\[(\d{{2}})-(\d{{2}}) (\d{{2}}):(\d{{2}}):\d{{2}}\][^\n]*{date_str}[^\n]*PARTIAL")
    matches = pattern.findall(text)
    if matches:
        mm, dd, hh, mi = matches[-1]
        return f"{mm}-{dd} {hh}:{mi}"
    return None


def count_csv_races(date_str):
    """CSVファイルからレース数を実測。"""
    path = os.path.join(BACKFILL_DIR, f"{date_str}.csv")
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        n = sum(1 for _ in f) - 1  # header
    return n // 120


def main():
    no_race = load_no_race()
    records = parse_log()

    print(f"=== 欠損実態分析 ===\n")
    print(f"ログから抽出した日数: {len(records)}")
    print(f"NO_RACE 日数: {len(no_race)}\n")

    # 失敗数別の分布
    buckets = {
        "0 (完璧OK)": 0,
        "1-2 (軽微)": 0,
        "3-5 (許容範囲)": 0,
        "6-15 (中程度欠損)": 0,
        "16-50 (重度欠損)": 0,
        "51+ (壊滅的)": 0,
    }
    heavy_losses = []  # >=10 失敗
    for date_str, rec in records.items():
        if rec["status"] == "NO_RACE":
            continue
        n = rec["failed"]
        if n == 0:
            buckets["0 (完璧OK)"] += 1
        elif n <= 2:
            buckets["1-2 (軽微)"] += 1
        elif n <= 5:
            buckets["3-5 (許容範囲)"] += 1
        elif n <= 15:
            buckets["6-15 (中程度欠損)"] += 1
        elif n <= 50:
            buckets["16-50 (重度欠損)"] += 1
        else:
            buckets["51+ (壊滅的)"] += 1

        if n >= 10:
            heavy_losses.append((date_str, n, rec["success_races"], rec["total_venues"]))

    print("--- 失敗レース数別の日数分布 ---")
    total = sum(buckets.values())
    for k, v in buckets.items():
        pct = v / total * 100 if total else 0
        print(f"  {k:25} : {v:4d} 日 ({pct:5.1f}%)")

    # 重大欠損トップ
    heavy_losses.sort(key=lambda x: x[1], reverse=True)
    print(f"\n--- 重大欠損 (失敗>=10) リスト (全{len(heavy_losses)}件、上位50) ---")
    print(f"  {'日付':>10} {'失敗':>5} {'成功':>5} {'開催場':>5}  処理時刻(JST)")
    for date_str, n_fail, n_succ, n_venues in heavy_losses[:50]:
        t = parse_log_time(date_str)
        total_races = n_venues * 12
        print(f"  {date_str:>10} {n_fail:>5} {n_succ:>5} {n_venues:>5}  {t or '-'}")

    # 朝バッチ被り判定（処理時刻が 08:30-10:00 の重大欠損のみ）
    print(f"\n--- 朝バッチ被り疑い (処理時刻 08:30-10:00 かつ 失敗>=10) ---")
    morning_collisions = []
    for date_str, n_fail, n_succ, n_venues in heavy_losses:
        t = parse_log_time(date_str)
        if t and " " in t:
            hhmm = t.split(" ", 1)[1]
            hh, mi = hhmm.split(":")
            if hh == "09" or (hh == "08" and int(mi) >= 30) or (hh == "10" and int(mi) == 0):
                morning_collisions.append((date_str, n_fail, n_succ, n_venues, t))
    for date_str, n_fail, n_succ, n_venues, t in morning_collisions:
        print(f"  {date_str:>10} 失敗={n_fail:>3} 成功={n_succ}/{n_venues*12}  処理時刻={t}")

    # 合計失敗レース数
    total_failed = sum(rec["failed"] for rec in records.values())
    total_targets = sum(rec["success_races"] + rec["failed"] for rec in records.values())
    print(f"\n--- 全体集計 ---")
    print(f"  期待レース総数: {total_targets:,}")
    print(f"  失敗レース総数: {total_failed:,}")
    print(f"  全体取得率: {(total_targets - total_failed) / total_targets * 100:.2f}%")

    # 再取得候補日リスト
    retry_threshold = 10
    retry_days = [d for d, rec in records.items() if rec["failed"] >= retry_threshold]
    retry_file = "logs/retry_candidates.txt"
    with open(retry_file, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(retry_days)))
    print(f"\n再取得候補({len(retry_days)}日, 失敗>={retry_threshold}) を {retry_file} に保存しました")


if __name__ == "__main__":
    main()
