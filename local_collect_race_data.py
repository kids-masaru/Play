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
    scrape_motor_stats,
    scrape_odds_3t,
    close_odds_browser,
    append_to_csv,
    RAW_RACE_DATA_HEADERS,
    HISTORY_RESULTS_HEADERS,
    RAW_BEFOREINFO_HEADERS,
    PLAYER_COURSE_STATS_HEADERS,
    MOTOR_STATS_HEADERS,
    ODDS_3T_HEADERS
)
import database as db

OUTPUT_DIR = "daily_data"
PROG_FILE = os.path.join(OUTPUT_DIR, "daily_raw_race_data.csv")
RES_FILE  = os.path.join(OUTPUT_DIR, "daily_history_results.csv")
BI_FILE   = os.path.join(OUTPUT_DIR, "daily_raw_beforeinfo.csv")
STATS_FILE = os.path.join(OUTPUT_DIR, "daily_player_course_stats.csv")
ODDS_FILE = os.path.join(OUTPUT_DIR, "daily_odds_3t.csv")

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

    # ----------------------------------------------------
    # Job 3: Today's Odds (当日の3連単確定オッズ)
    # ----------------------------------------------------
    print(f"\n>>> Job 3: 当日の3連単確定オッズを取得します")

    # 結果と同じ日付のオッズを取得（当日のレースが終了しているので確定オッズ）
    odds_date_str = result_date_str  # Job 2 と同じ日付
    odds_date_csv_format = result_date.strftime("%Y-%m-%d")
    print(f"  > 対象日: {odds_date_str}")

    is_odds_skipped = False
    if os.path.exists(ODDS_FILE):
        import pandas as pd
        df_o = pd.read_csv(ODDS_FILE)
        if odds_date_csv_format in df_o['Date'].astype(str).values:
            print(f"  > [SKIP] {odds_date_csv_format} のオッズは既に取得済みです。")
            is_odds_skipped = True

    venues_odds = []
    if not is_odds_skipped:
        venues_odds = get_venues_for_date(odds_date_str) if not venues_result else venues_result

    if venues_odds:
        print(f"  > 開催会場({len(venues_odds)}): {venues_odds}")

        # 既存データをチェック（レジューム対応）
        done_venues_odds = set()
        if os.path.exists(ODDS_FILE):
            df_odds_ex = pd.read_csv(ODDS_FILE)
            mask_o = df_odds_ex['Date'] == odds_date_csv_format
            done_venues_odds = set(df_odds_ex[mask_o]['Venue'].astype(str).unique())

        from collect_race_data import VENUE_MAP

        for jcd in venues_odds:
            v_name = VENUE_MAP.get(jcd, jcd)
            if v_name in done_venues_odds:
                print(f"    - 会場 {v_name} ({jcd})... [SKIP] 取得済み")
                continue

            print(f"    - 会場 {v_name} ({jcd})... ", end="", flush=True)
            day_odds_rows = []

            for rno in range(1, 13):
                time.sleep(0.3)
                o_rows = scrape_odds_3t(jcd, rno, odds_date_str)
                if o_rows:
                    day_odds_rows.extend(o_rows)

            # 会場ごとに保存
            if day_odds_rows:
                append_to_csv(ODDS_FILE, ODDS_3T_HEADERS, day_odds_rows)
            print(f"完了 ({len(day_odds_rows)}行)")
    elif not is_odds_skipped:
        print(f"  > 対象日の開催会場はありません。")

    # オッズ取得用ブラウザのクリーンアップ
    close_odds_browser()

    # ----------------------------------------------------
    # Job 4: モーター成績の取得 (Phase 4)
    # ----------------------------------------------------
    print(f"\n>>> Job 4: モーター成績を取得します")
    # 翌日の開催会場のモーター成績を取得（予測用）
    motor_venues = venues_program if venues_program else []
    if not motor_venues and not is_prog_skipped:
        motor_venues = get_venues_for_date(program_date_str)

    db.ensure_db()

    if motor_venues:
        print(f"  > 対象会場({len(motor_venues)}): {motor_venues}")
        for jcd in motor_venues:
            from collect_race_data import VENUE_MAP
            v_name = VENUE_MAP.get(jcd, jcd)
            # DBに既に最新データがあればスキップ
            existing = db.get_motor_stats_by_venue(v_name)
            if not existing.empty:
                latest_date = existing['UpdatedDate'].max()
                if latest_date == program_date.strftime("%Y-%m-%d"):
                    print(f"    - 会場 {v_name}... [SKIP] 最新データあり")
                    continue

            print(f"    - 会場 {v_name} ({jcd})... ", end="", flush=True)
            time.sleep(0.5)
            motor_rows = scrape_motor_stats(jcd, program_date_str)
            if motor_rows:
                db.insert_motor_stats(motor_rows)
                print(f"完了 ({len(motor_rows)}モーター)")
            else:
                print("データなし")
    else:
        print(f"  > モーター成績取得対象の会場はありません。")

    # ----------------------------------------------------
    # DB同期: 取得データをSQLiteにも保存
    # ----------------------------------------------------
    print(f"\n>>> DB同期: 取得データをSQLiteに保存します")
    _sync_csv_to_db()

    print("\n=== ローカル版 データ収集 正常終了 ===")


def _sync_csv_to_db():
    """daily_dataのCSVをDBにも同期する"""
    db.ensure_db()

    import pandas as pd

    csv_db_map = [
        (PROG_FILE, "races", db.RACE_COLUMNS, {"ID": "RaceID"}),
        (RES_FILE, "results", db.RESULT_COLUMNS, {"ID": "RaceID"}),
        (BI_FILE, "beforeinfo", db.BEFOREINFO_COLUMNS, {"ID": "RaceID"}),
        (STATS_FILE, "player_stats", db.PLAYER_STATS_COLUMNS, {}),
        (ODDS_FILE, "odds", db.ODDS_COLUMNS, {"ID": "RaceID"}),
    ]

    for csv_file, table, columns, col_map in csv_db_map:
        if not os.path.exists(csv_file):
            continue
        try:
            df = pd.read_csv(csv_file, dtype=str)
            if df.empty:
                continue
            if col_map:
                df = df.rename(columns=col_map)
            for col in columns:
                if col not in df.columns:
                    df[col] = ''
            rows = df[columns].fillna('').values.tolist()
            db.insert_rows(table, columns, rows)
            print(f"  ✅ {os.path.basename(csv_file)} → {table}: {len(rows)} 行同期")
        except Exception as e:
            print(f"  [WARN] {os.path.basename(csv_file)} 同期失敗: {e}")


if __name__ == "__main__":
    main()
