import os
import time
from datetime import datetime, timedelta, timezone

# collect_race_data.pyの既存スクレイピング関数（Google Sheets非依存の純粋な関数）を流用
from collect_race_data import (
    get_venues_for_date,
    scrape_program,
    scrape_result_venue,
    scrape_beforeinfo,
    scrape_player_course_stats,
    append_to_csv,
    RAW_RACE_DATA_HEADERS,
    HISTORY_RESULTS_HEADERS,
    RAW_BEFOREINFO_HEADERS,
    PLAYER_COURSE_STATS_HEADERS
)

OUTPUT_DIR = "daily_data"
PROG_FILE = os.path.join(OUTPUT_DIR, "daily_raw_race_data.csv")
RES_FILE  = os.path.join(OUTPUT_DIR, "daily_history_results.csv")
BI_FILE   = os.path.join(OUTPUT_DIR, "daily_raw_beforeinfo.csv")
STATS_FILE = os.path.join(OUTPUT_DIR, "daily_player_course_stats.csv")

def main():
    print("=== STEP 1 & 2: 完全ローカル版 日次データ収集開始 ===")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)

    # ----------------------------------------------------
    # Job 1: Tomorrow's Program (翌日の出走表を取得)
    # ----------------------------------------------------
    print(f"\n>>> Job 1: 翌日の出走表(Program)を取得します")
    
    if now_jst.hour >= 18:
        # 18時以降の実行なら翌日の番組
        program_date = now_jst + timedelta(days=1)
    else:
        # それ以前なら基本当日の番組（タスクは23時想定）
        program_date = now_jst
        
    program_date_str = program_date.strftime("%Y%m%d")
    print(f"  > 対象日: {program_date_str}")
    
    # すでに取得済みかチェック
    program_date_csv_format = program_date.strftime("%Y-%m-%d")
    is_prog_skipped = False
    if os.path.exists(PROG_FILE):
        import pandas as pd
        df_p = pd.read_csv(PROG_FILE)
        if program_date_csv_format in df_p['Date'].astype(str).values:
            print(f"  > [SKIP] {program_date_csv_format} の出走表は既に取得済みです。")
            is_prog_skipped = True
            
    venues_program = []
    if not is_prog_skipped:
        venues_program = get_venues_for_date(program_date_str)
            
    if venues_program:
        print(f"  > 開催会場({len(venues_program)}): {venues_program}")
        
        # 既存データを読み込んで、どの会場まで終わっているか把握する（レジューム対応）
        done_venues_prog = set()
        if os.path.exists(PROG_FILE):
            df_existing = pd.read_csv(PROG_FILE)
            mask = df_existing['Date'] == program_date_csv_format
            done_venues_prog = set(df_existing[mask]['Venue'].astype(str).unique())
            # Venueマッピングの逆引きが必要（JCD <-> 漢字名）
            # 簡略化のため、JCDそのままで判定できるように、内部のVENUE_MAPを逆引き可能にするか、IDで判定
            # scrape_programの結果のVenue列は漢字なので注意
        
        from collect_race_data import VENUE_MAP
        INV_VENUE_MAP = {v: k for k, v in VENUE_MAP.items()}

        for jcd in venues_program:
            v_name = VENUE_MAP.get(jcd, jcd)
            if v_name in done_venues_prog:
                print(f"    - 会場 {v_name} ({jcd})... [SKIP] 取得済み")
                continue
                
            print(f"    - 会場 {v_name} ({jcd})... ", end="", flush=True)
            day_prog_rows = []
            venue_rows = 0
            for rno in range(1, 13):
                time.sleep(0.3)
                rows = scrape_program(jcd, rno, program_date_str)
                if rows:
                    day_prog_rows.extend(rows)
                    venue_rows += len(rows)
            
            # 会場ごとに保存
            if day_prog_rows:
                append_to_csv(PROG_FILE, RAW_RACE_DATA_HEADERS, day_prog_rows)
            print(f"完了 ({venue_rows}行)")

        # 出走選手リストを再取得（STATS収集のため）
        if os.path.exists(PROG_FILE):
            df_reprog = pd.read_csv(PROG_FILE)
            day_prog_rows_all = df_reprog[df_reprog['Date'] == program_date_csv_format].values.tolist()
        else:
            day_prog_rows_all = []

        # ----------------------------------------------------
        # Job 1.5: Player Course Stats (出走選手のコース別成績)
        # ----------------------------------------------------
        print(f"\n>>> Job 1.5: 出走選手のコース別成績(Course Stats)を取得します")
        player_ids = sorted(list(set([row[5] for row in day_prog_rows_all if row[5]])))
        print(f"  > 対象選手数: {len(player_ids)}名")
        
        # 既存の統計データを読み込んで重複を避ける（簡易レジューム）
        existing_players = set()
        if os.path.exists(STATS_FILE):
            import pandas as pd
            df_s = pd.read_csv(STATS_FILE)
            existing_players = set(df_s['PlayerID'].astype(str).unique())
            
        stats_rows = []
        for pid in player_ids:
            if str(pid) in existing_players:
                continue
            print(f"    - 選手 {pid}... ", end="", flush=True)
            time.sleep(0.5) # 負荷軽減
            p_stats = scrape_player_course_stats(pid)
            if p_stats:
                stats_rows.append(p_stats)
                print("完了")
            else:
                print("失敗")
        
        if stats_rows:
            append_to_csv(STATS_FILE, PLAYER_COURSE_STATS_HEADERS, stats_rows)
            print(f"  > {STATS_FILE} に {len(stats_rows)} 名分のデータを保存しました。")
        else:
            print("  > 新たに取得が必要な選手はいませんでした。")

    elif not is_prog_skipped:
        print(f"  > 対象日の開催会場はありません。")

    # ----------------------------------------------------
    # Job 2: Today's Results & BeforeInfo (当日の結果・直前情報)
    # ----------------------------------------------------
    print(f"\n>>> Job 2: 当日の結果(Result)と直前情報(BeforeInfo)を取得します")
    
    # 実際は18時以降の夜間に動作するため、当日の結果をフェッチ
    if now_jst.hour >= 18:
        result_date = now_jst
    else:
        result_date = now_jst - timedelta(days=1)
        
    result_date_str = result_date.strftime("%Y%m%d")
    print(f"  > 対象日: {result_date_str}")
    
    # すでに取得済みかチェック
    result_date_csv_format = result_date.strftime("%Y-%m-%d")
    is_res_skipped = False
    if os.path.exists(RES_FILE):
        import pandas as pd
        df_r = pd.read_csv(RES_FILE)
        if result_date_csv_format in df_r['Date'].astype(str).values:
            print(f"  > [SKIP] {result_date_csv_format} の結果・直前情報は既に取得済みです。")
            is_res_skipped = True

    venues_result = []
    if not is_res_skipped:
        venues_result = get_venues_for_date(result_date_str)
    
    if venues_result:
        print(f"  > 開催会場({len(venues_result)}): {venues_result}")
        
        # 既存データをチェック（レジューム対応）
        done_venues_res = set()
        if os.path.exists(RES_FILE):
            df_res_ex = pd.read_csv(RES_FILE)
            mask_r = df_res_ex['Date'] == result_date_csv_format
            done_venues_res = set(df_res_ex[mask_r]['Venue'].astype(str).unique())

        from collect_race_data import VENUE_MAP
        
        for jcd in venues_result:
            v_name = VENUE_MAP.get(jcd, jcd)
            if v_name in done_venues_res:
                print(f"    - 会場 {v_name} ({jcd})... [SKIP] 取得済み")
                continue

            print(f"    - 会場 {v_name} ({jcd})... ", end="", flush=True)
            day_res_rows = []
            day_bi_rows = []
            
            # 結果
            time.sleep(0.5)
            r_rows = scrape_result_venue(jcd, result_date_str)
            if r_rows: day_res_rows.extend(r_rows)
            
            # 直前情報
            for rno in range(1, 13):
                time.sleep(0.3)
                b_rows = scrape_beforeinfo(jcd, rno, result_date_str)
                if b_rows: day_bi_rows.extend(b_rows)
            
            # 会場ごとに保存
            if day_res_rows:
                append_to_csv(RES_FILE, HISTORY_RESULTS_HEADERS, day_res_rows)
            if day_bi_rows:
                append_to_csv(BI_FILE, RAW_BEFOREINFO_HEADERS, day_bi_rows)
                
            print("完了")
    elif not is_res_skipped:
        print(f"  > 対象日の開催会場はありません。")

    print("\n=== ローカル版 データ収集 正常終了 ===")

if __name__ == "__main__":
    main()
