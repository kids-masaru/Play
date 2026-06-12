"""重大欠損日(失敗>=16レース)の再取得スクリプト。

scrape_past_odds_parallel.py の worker_thread 等を再利用。
既存CSVは past_data/past_odds_3t_backfill_old/ に退避してから再取得。
"""
import os
import csv
import shutil
import time
import threading
import queue
import re
from datetime import datetime

# sys.stdout の utf-8 化は scrape_past_odds_parallel の import 時に行われる
from collect_race_data import get_venues_for_date, VENUE_MAP
from scrape_past_odds_parallel import (
    worker_thread,
    save_day_csv,
    log as _,  # 別logを使うので未使用
    OUTPUT_DIR,
)

# === 設定 ===
N_WORKERS = 3
LOSS_THRESHOLD = 16  # 失敗 >= この値の日を再取得対象
ORIG_LOG = os.path.join("logs", "backfill_odds.log")
OLD_DIR = os.path.join("past_data", "past_odds_3t_backfill_old")
LOG_FILE = os.path.join("logs", "retry_failed_days.log")

_log_lock = threading.Lock()


def log(msg):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with _log_lock:
        print(line, flush=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def load_target_days():
    """元ログから 失敗>=LOSS_THRESHOLD の日付リストを抽出。"""
    LINE_RE = re.compile(
        r"\[\s*\d+/\d+\]\s+(\d{8})\s+PARTIAL\((\d+)"
    )
    with open(ORIG_LOG, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")
    targets = []
    for line in text.split("\n"):
        m = LINE_RE.search(line)
        if m:
            date_str = m.group(1)
            n_failed = int(m.group(2))
            if n_failed >= LOSS_THRESHOLD:
                targets.append((date_str, n_failed))
    targets.sort()
    return targets


def backup_existing(date_str):
    """既存CSVを退避ディレクトリにコピー。"""
    src = os.path.join(OUTPUT_DIR, f"{date_str}.csv")
    if not os.path.exists(src):
        return False
    os.makedirs(OLD_DIR, exist_ok=True)
    dst = os.path.join(OLD_DIR, f"{date_str}.csv")
    shutil.copy2(src, dst)
    return True


def count_races(csv_path):
    if not os.path.exists(csv_path):
        return 0
    with open(csv_path, "r", encoding="utf-8") as f:
        n = sum(1 for _ in f) - 1
    return n // 120


def main():
    os.makedirs("logs", exist_ok=True)
    os.makedirs(OLD_DIR, exist_ok=True)
    # ログ初期化
    open(LOG_FILE, "w", encoding="utf-8").close()

    targets = load_target_days()
    log(f"=== 重大欠損日 再取得 開始 ===")
    log(f"対象日数: {len(targets)} 日 (失敗>={LOSS_THRESHOLD})")
    log(f"並列度: {N_WORKERS}")

    # ワーカースレッド起動
    task_q = queue.Queue()
    done_q = queue.Queue()
    threads = []
    for i in range(N_WORKERS):
        t = threading.Thread(target=worker_thread, args=(i, task_q, done_q), daemon=True)
        t.start()
        threads.append(t)
    log("ワーカー起動中...")
    time.sleep(5)  # ブラウザ起動待ち

    t_start = time.time()
    improved = 0
    same = 0
    worse = 0
    comparison_rows = []

    try:
        for i, (date_str, orig_failed) in enumerate(targets, 1):
            t_day = time.time()
            old_csv = os.path.join(OUTPUT_DIR, f"{date_str}.csv")
            old_races = count_races(old_csv)

            backup_existing(date_str)

            try:
                venues = get_venues_for_date(date_str)
            except Exception as e:
                log(f"[{i}/{len(targets)}] {date_str} venues取得失敗: {e}")
                continue
            if not venues:
                log(f"[{i}/{len(targets)}] {date_str} 開催無し? スキップ")
                continue

            n_tasks = 0
            for jcd in venues:
                for rno in range(1, 13):
                    task_q.put((date_str, jcd, rno))
                    n_tasks += 1
            expected = len(venues) * 12

            day_rows = []
            failed_now = 0
            for _ in range(n_tasks):
                ds, jcd, rno, rows = done_q.get()
                if len(rows) == 120 and sum(1 for r in rows if r[5] > 0) >= 100:
                    day_rows.extend(rows)
                else:
                    failed_now += 1

            new_races = len(day_rows) // 120
            elapsed = time.time() - t_day

            if day_rows:
                save_day_csv(date_str, day_rows)

            delta = new_races - old_races
            if delta > 0:
                improved += 1
                tag = f"IMPROVED(+{delta})"
            elif delta == 0:
                same += 1
                tag = "SAME"
            else:
                worse += 1
                tag = f"WORSE({delta})"

            comparison_rows.append({
                "date": date_str,
                "expected": expected,
                "old_races": old_races,
                "new_races": new_races,
                "old_failed": orig_failed,
                "new_failed": failed_now,
                "delta": delta,
                "tag": tag,
            })

            total_elapsed = time.time() - t_start
            eta = (len(targets) - i) * (total_elapsed / i) / 60
            log(
                f"[{i:3d}/{len(targets)}] {date_str} {tag} "
                f"old={old_races} new={new_races}/{expected} "
                f"({elapsed:.0f}s) ETA {eta:.1f}min"
            )
    finally:
        log("シャットダウン信号送信...")
        for _ in range(N_WORKERS):
            task_q.put(None)
        for t in threads:
            t.join(timeout=30)

    # 結果サマリ
    log("")
    log("=== 再取得サマリ ===")
    log(f"改善: {improved} 日")
    log(f"同等: {same} 日")
    log(f"悪化: {worse} 日")
    log(f"所要時間: {(time.time()-t_start)/60:.1f} 分")

    # 詳細レポートをCSV出力
    report_csv = "logs/retry_comparison.csv"
    with open(report_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date","expected","old_races","new_races",
                                            "old_failed","new_failed","delta","tag"])
        w.writeheader()
        w.writerows(comparison_rows)
    log(f"詳細レポート: {report_csv}")


if __name__ == "__main__":
    main()
