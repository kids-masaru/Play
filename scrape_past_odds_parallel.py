"""過去オッズ全期間取得スクリプト (並列度3、各スレッド独立ブラウザ)。

期間: 2024-12-01 〜 2026-05-29 (約1年6ヶ月)
出力: past_data/past_odds_3t_backfill/YYYYMMDD.csv (日別)
レジューム: 既存日別CSVが揃ってる日はスキップ
無開催日: past_data/past_odds_3t_backfill/no_race.txt にマーク
進捗ログ: logs/backfill_odds.log

設計:
- ワーカースレッドが自分でPlaywrightブラウザを起動する（メインスレッドはPlaywrightに触らない）
- タスクは (date_str, jcd, rno) のタプル
- 結果は done_q に投入、メインが日付ごとに集計してCSV保存
"""
import os
import sys
import io
import csv
import time
import threading
import queue
from datetime import datetime, date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from collect_race_data import get_venues_for_date, VENUE_MAP

# === 設定 ===
START_DATE = date(2024, 12, 1)
END_DATE = date(2026, 5, 29)
N_WORKERS = 3
SLEEP_BETWEEN_RACES = 0.3   # 1レース後の小休止(秒)
ODDS_WAIT_MAX = 6.0
ODDS_WAIT_STEP = 0.5

OUTPUT_DIR = os.path.join("past_data", "past_odds_3t_backfill")
LOG_FILE = os.path.join("logs", "backfill_odds.log")
NO_RACE_FILE = os.path.join(OUTPUT_DIR, "no_race.txt")

_log_lock = threading.Lock()


def log(msg):
    ts = datetime.now().strftime("%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with _log_lock:
        print(line, flush=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def get_combos_for_first(first):
    others = [b for b in range(1, 7) if b != first]
    combos = []
    for second in others:
        thirds = [b for b in range(1, 7) if b != first and b != second]
        for third in thirds:
            combos.append((first, second, third))
    return combos

BLOCK_COMBOS = [get_combos_for_first(f) for f in range(1, 7)]


def scrape_one(page, jcd, rno, date_str):
    """1レース取得。page は呼び出し側で管理。成功時120行、失敗時空。"""
    venue_name = VENUE_MAP.get(jcd, f"V{jcd}")
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    race_id = f"{date_str}_{venue_name}_{rno}"
    url = f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno={rno}&jcd={jcd}&hd={date_str}"

    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        steps = int(ODDS_WAIT_MAX / ODDS_WAIT_STEP)
        for _ in range(steps):
            time.sleep(ODDS_WAIT_STEP)
            cells = page.query_selector_all('td.oddsPoint')
            if cells:
                sample = cells[len(cells)//2].inner_text().strip()
                if sample and sample != '0.0':
                    break
        cells = page.query_selector_all('td.oddsPoint')
        if not cells:
            return []
        rows = []
        for row_idx in range(20):
            for block_idx in range(6):
                cell_idx = row_idx * 6 + block_idx
                if cell_idx >= len(cells):
                    continue
                odds_text = cells[cell_idx].inner_text().strip()
                try:
                    odds_val = float(odds_text)
                except (ValueError, TypeError):
                    odds_val = 0.0
                combo = BLOCK_COMBOS[block_idx][row_idx]
                combo_str = f"{combo[0]}-{combo[1]}-{combo[2]}"
                rows.append([race_id, display_date, venue_name, rno, combo_str, odds_val])
        return rows
    except Exception as e:
        return []


def worker_thread(wid, task_q, done_q):
    """ワーカースレッド。自分でPlaywrightを起動して常駐。
    None タスクで終了。
    """
    from playwright.sync_api import sync_playwright
    pw = None
    br = None
    page = None
    try:
        pw = sync_playwright().start()
        br = pw.chromium.launch(headless=True)
        ctx = br.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = ctx.new_page()
        log(f"  [W{wid}] ブラウザ起動完了")

        while True:
            task = task_q.get()
            if task is None:
                task_q.task_done()
                break
            date_str, jcd, rno = task
            rows = scrape_one(page, jcd, rno, date_str)
            done_q.put((date_str, jcd, rno, rows))
            task_q.task_done()
            time.sleep(SLEEP_BETWEEN_RACES)
    except Exception as e:
        log(f"  [W{wid} FATAL] {type(e).__name__}: {e}")
    finally:
        try:
            if br: br.close()
        except Exception: pass
        try:
            if pw: pw.stop()
        except Exception: pass
        log(f"  [W{wid}] 終了")


def load_no_race_set():
    if not os.path.exists(NO_RACE_FILE):
        return set()
    with open(NO_RACE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def is_day_complete(date_str):
    """その日のCSVが既に正常完了しているか判定。"""
    out_csv = os.path.join(OUTPUT_DIR, f"{date_str}.csv")
    if not os.path.exists(out_csv):
        return False
    try:
        with open(out_csv, "r", encoding="utf-8") as f:
            n_lines = sum(1 for _ in f) - 1
        return n_lines >= 120  # 最低1レース以上
    except Exception:
        return False


def save_day_csv(date_str, all_rows):
    out_csv = os.path.join(OUTPUT_DIR, f"{date_str}.csv")
    tmp = out_csv + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Date", "Venue", "R", "Combination", "Odds"])
        w.writerows(all_rows)
    os.replace(tmp, out_csv)


def mark_no_race(date_str):
    with _log_lock:
        with open(NO_RACE_FILE, "a", encoding="utf-8") as f:
            f.write(date_str + "\n")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    log(f"=== 過去オッズ全期間取得 開始 (並列度{N_WORKERS}) ===")
    log(f"期間: {START_DATE} 〜 {END_DATE}")

    # キューとスレッド準備
    task_q = queue.Queue()
    done_q = queue.Queue()
    threads = []
    for i in range(N_WORKERS):
        t = threading.Thread(target=worker_thread, args=(i, task_q, done_q), daemon=True)
        t.start()
        threads.append(t)
    log(f"ワーカースレッド{N_WORKERS}個起動")
    time.sleep(3)  # ブラウザ起動を少し待つ

    # 日付リスト
    date_list = []
    d = START_DATE
    while d <= END_DATE:
        date_list.append(d)
        d += timedelta(days=1)
    log(f"対象日数: {len(date_list)} 日")

    no_race_set = load_no_race_set()

    t_start = time.time()
    skipped = 0
    no_race = 0
    ok = 0
    partial = 0
    failed_days = 0
    total_rows = 0

    try:
        for i, dobj in enumerate(date_list, 1):
            date_str = dobj.strftime("%Y%m%d")

            if is_day_complete(date_str):
                skipped += 1
                continue
            if date_str in no_race_set:
                skipped += 1
                continue

            t_day = time.time()
            try:
                venues = get_venues_for_date(date_str)
            except Exception as e:
                log(f"[{i}/{len(date_list)}] {date_str} venues取得失敗: {e}")
                failed_days += 1
                continue

            if not venues:
                mark_no_race(date_str)
                no_race_set.add(date_str)
                no_race += 1
                log(f"[{i:4d}/{len(date_list)}] {date_str} NO_RACE")
                continue

            # タスク投入
            n_tasks = 0
            for jcd in venues:
                for rno in range(1, 13):
                    task_q.put((date_str, jcd, rno))
                    n_tasks += 1

            # n_tasks 件の結果を受信
            day_rows = []
            failed_races = []
            for _ in range(n_tasks):
                ds, jcd, rno, rows = done_q.get()
                if len(rows) == 120 and sum(1 for r in rows if r[5] > 0) >= 100:
                    day_rows.extend(rows)
                else:
                    failed_races.append((jcd, rno, len(rows)))

            elapsed = time.time() - t_day
            if day_rows:
                save_day_csv(date_str, day_rows)
                if failed_races:
                    partial += 1
                    tag = f"PARTIAL({len(failed_races)}失敗)"
                else:
                    ok += 1
                    tag = "OK"
                total_rows += len(day_rows)
            else:
                failed_days += 1
                tag = "FAIL"

            total_elapsed = time.time() - t_start
            remaining = len(date_list) - i
            done_real = ok + partial + no_race + failed_days
            if done_real > 0:
                avg = total_elapsed / done_real
                eta_h = remaining * avg / 3600
            else:
                eta_h = 0.0

            log(
                f"[{i:4d}/{len(date_list)}] {date_str} {tag} "
                f"races={len(day_rows)//120}/{n_tasks//12 if n_tasks else 0}場 "
                f"rows={len(day_rows)} ({elapsed:.0f}s) "
                f"| 累計 {total_elapsed/3600:.1f}h ETA {eta_h:.1f}h "
                f"| OK={ok} PART={partial} NORACE={no_race} SKIP={skipped} FAIL={failed_days}"
            )
    finally:
        log("シャットダウン信号送信…")
        for _ in range(N_WORKERS):
            task_q.put(None)
        for t in threads:
            t.join(timeout=30)

    log("=== 完了 ===")
    log(f"OK={ok} PARTIAL={partial} NORACE={no_race} SKIP={skipped} FAIL={failed_days}")
    log(f"取得行数合計: {total_rows:,}")
    log(f"全所要時間: {(time.time()-t_start)/3600:.2f}時間")


if __name__ == "__main__":
    main()
