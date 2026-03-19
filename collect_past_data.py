"""
過去数年分のボートレースデータを一括取得してCSVに保存するスクリプト。
機械学習（LightGBM等）の教師データ作成用。

使用方法:
python collect_past_data.py
"""
import os
import time
import requests
import csv
from datetime import datetime, timedelta
# 既存のスクレイパー処理を再利用
from collect_race_data import (
    get_venues_for_date, 
    scrape_program, 
    scrape_result_venue, 
    scrape_beforeinfo, 
    append_to_csv,
    RAW_RACE_DATA_HEADERS, 
    RAW_BEFOREINFO_HEADERS, 
    HISTORY_RESULTS_HEADERS
)

# --- 設定 ---
# 取得期間を設定 (例: 2023年1月1日 〜 2024年12月31日)
# TODO: テスト時は以下の期間でした
# START_DATE_STR = "2024-12-01"
# END_DATE_STR   = "2024-12-05" 

# 本番収集用（2025年分）
START_DATE_STR = "2025-01-01"
END_DATE_STR   = "2025-12-31" 

OUTPUT_DIR = "past_data"

def daterange(start_date, end_date):
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + timedelta(n)

def get_collected_dates(csv_file):
    """既にCSVに保存済みの日付一覧を取得する（レジューム用）"""
    dates = set()
    if not os.path.isfile(csv_file):
        return dates
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)  # ヘッダーをスキップ
            for row in reader:
                if row and row[0]:
                    dates.add(row[0])  # Date列（YYYY-MM-DD形式）
    except Exception as e:
        print(f"  [WARN] 既存CSV読み込みエラー: {e}")
    return dates

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    prog_file = os.path.join(OUTPUT_DIR, "past_race_data.csv")
    res_file  = os.path.join(OUTPUT_DIR, "past_history_results.csv")
    bi_file   = os.path.join(OUTPUT_DIR, "past_raw_beforeinfo.csv")

    start_date = datetime.strptime(START_DATE_STR, "%Y-%m-%d").date()
    end_date   = datetime.strptime(END_DATE_STR, "%Y-%m-%d").date()
    
    # レジューム: 既存CSVから収集済み日付を取得してスキップ
    collected_dates = get_collected_dates(prog_file)
    if collected_dates:
        print(f"=== レジューム検出: {len(collected_dates)} 日分が収集済み ===")
        print(f"  最終収集日: {sorted(collected_dates)[-1]}")
        print(f"  収集済み日付はスキップして続行します。")
    
    print(f"\n=== 過去データ収集開始 ===")
    print(f"期間: {start_date} 〜 {end_date}")
    print(f"保存先: {OUTPUT_DIR}/")
    
    total_days = (end_date - start_date).days + 1
    processed_days = 0

    for single_date in daterange(start_date, end_date):
        date_str = single_date.strftime("%Y%m%d")
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        processed_days += 1
        
        # レジューム: 収集済みの日はスキップ
        if display_date in collected_dates:
            print(f"[{processed_days}/{total_days}] {date_str} → 収集済み。スキップ。")
            continue
        
        print(f"\n[{processed_days}/{total_days}] 日付: {date_str} のデータを取得中...")
        
        venues = get_venues_for_date(date_str)
        if not venues:
            print(f"  > 開催会場なし。スキップします。")
            continue
            
        print(f"  > 開催会場({len(venues)}): {venues}")
        
        day_prog_rows = []
        day_res_rows = []
        day_bi_rows = []
        
        for jcd in venues:
            print(f"    - 会場 {jcd}... ", end="", flush=True)
            venue_success = True
            
            # 1. 出走表(Program)
            for rno in range(1, 13):
                time.sleep(0.3)  # サーバー負荷軽減のための待機
                rows = scrape_program(jcd, rno, date_str)
                if rows: day_prog_rows.extend(rows)
            
            # 2. 結果(Result)
            time.sleep(0.5)
            res_rows = scrape_result_venue(jcd, date_str)
            if res_rows: day_res_rows.extend(res_rows)
            
            # 3. 直前情報(BeforeInfo)
            for rno in range(1, 13):
                time.sleep(0.3)
                bi_rows = scrape_beforeinfo(jcd, rno, date_str)
                if bi_rows: day_bi_rows.extend(bi_rows)
                
            print(f"完了 (出走表:{len(day_prog_rows)}行, 結果:{len(day_res_rows)}行, 直前:{len(day_bi_rows)}行)")

        # 一日分終わるごとにCSVに追記保存 (途中でエラーで止まってもデータが残るように)
        append_to_csv(prog_file, RAW_RACE_DATA_HEADERS, day_prog_rows)
        append_to_csv(res_file, HISTORY_RESULTS_HEADERS, day_res_rows)
        append_to_csv(bi_file, RAW_BEFOREINFO_HEADERS, day_bi_rows)
        
        print(f"  > {date_str} のデータをCSVに保存しました。")
        
        # 連続リクエストを避けるための1日の間の待機
        time.sleep(2)

    print("\n=== 全ての日程のデータ収集が完了しました ===")

if __name__ == "__main__":
    main()
