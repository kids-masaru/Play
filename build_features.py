import os
import pandas as pd
import numpy as np
import database as db

# --- 設定 ---
INPUT_DIR = "past_data"
PROG_FILE = os.path.join(INPUT_DIR, "past_race_data.csv")
INFO_FILE = os.path.join(INPUT_DIR, "past_raw_beforeinfo.csv")
RES_FILE  = os.path.join(INPUT_DIR, "past_history_results.csv")
STATS_FILE = os.path.join(INPUT_DIR, "past_player_course_stats.csv") # 過去データ用
# 日次データ用の場所も考慮
DAILY_STATS_FILE = os.path.join("daily_data", "daily_player_course_stats.csv")
OUTPUT_FILE = os.path.join(INPUT_DIR, "ml_features.csv")

def clean_numeric(val):
    if pd.isna(val) or val == "": return np.nan
    try:
        # 文字列から数字と小数点、ハイフン以外を除去
        s = ''.join(c for c in str(val) if c.isdigit() or c in ['.', '-'])
        return float(s) if s else np.nan
    except:
        return np.nan

def rank_to_score(rank_str):
    mapping = {"A1": 4, "A2": 3, "B1": 2, "B2": 1}
    return mapping.get(str(rank_str).upper(), 0)

def extract_1st_place(result_str):
    """'1-2-3' などの結果文字列から1着の艇番(1)を抽出"""
    if pd.isna(result_str): return np.nan
    parts = str(result_str).split('-')
    if len(parts) >= 1 and parts[0].isdigit():
        return int(parts[0])
    return np.nan

def extract_2nd_place(result_str):
    """'1-2-3' などの結果文字列から2着の艇番(2)を抽出"""
    if pd.isna(result_str): return np.nan
    parts = str(result_str).split('-')
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return np.nan

def extract_3rd_place(result_str):
    """'1-2-3' などの結果文字列から3着の艇番(3)を抽出"""
    if pd.isna(result_str): return np.nan
    parts = str(result_str).split('-')
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return np.nan

def main():
    print("=== 特徴量エンジニアリング（学習データ作成）開始 ===")

    # Phase 4: DB優先、CSVフォールバック
    use_db = db.db_exists()
    if use_db:
        print("データベースからデータを読み込んでいます...")
        df_prog = db.query_df("SELECT Date, Venue, R, RaceID AS ID, Lane, PlayerID, Name, Motor, Rank, WinRate, Count FROM races")
        df_info = db.query_df("SELECT RaceID AS ID, Date, Venue, R, Weather, WindSpeed, WindDir, Wave, WaterTemp, "
                              "B1_Weight, B1_Tilt, B1_ExTime, B2_Weight, B2_Tilt, B2_ExTime, "
                              "B3_Weight, B3_Tilt, B3_ExTime, B4_Weight, B4_Tilt, B4_ExTime, "
                              "B5_Weight, B5_Tilt, B5_ExTime, B6_Weight, B6_Tilt, B6_ExTime FROM beforeinfo")
        df_res = db.query_df("SELECT Date, Venue, R, RaceID AS ID, Result, Payout FROM results")
        df_stats = db.get_all_player_stats()

        # モーター成績の追加（Phase 4 新機能）
        df_motor = db.query_df("SELECT * FROM motor_stats")

        if df_prog.empty or df_res.empty or df_info.empty:
            print("エラー: データベースに十分なデータがありません。CSVにフォールバックします。")
            use_db = False

    if not use_db:
        if not os.path.exists(PROG_FILE) or not os.path.exists(RES_FILE) or not os.path.exists(INFO_FILE):
            print("エラー: past_data フォルダに必要なCSVファイルが揃っていません。")
            return

        # 1. データ読み込み
        print("CSVからデータを読み込んでいます...")
        df_prog = pd.read_csv(PROG_FILE)
        df_info = pd.read_csv(INFO_FILE)
        df_res  = pd.read_csv(RES_FILE)
        df_motor = pd.DataFrame()

        # コース別成績の読み込み（過去分と日次分をマージ）
        df_stats = pd.DataFrame()
        if os.path.exists(STATS_FILE):
            df_stats = pd.read_csv(STATS_FILE)
        if os.path.exists(DAILY_STATS_FILE):
            df_ds = pd.read_csv(DAILY_STATS_FILE)
            df_stats = pd.concat([df_stats, df_ds]).drop_duplicates(subset=['PlayerID'], keep='last')

    # 2. 出走表データ (df_prog) にコース別成績を紐付け
    print("出走表に選手のコース別成績を紐付けています...")
    if not df_stats.empty:
        # 1-6号艇それぞれのレーン番号に応じた成績を抽出
        # まずはPlayerIDで全成績をマージ
        df_prog = pd.merge(df_prog, df_stats, on='PlayerID', how='left')
        
        # 実際にそのレースで走る Lane (1-6) に応じた Win/2in/3in を抽出
        def get_lane_stats(row):
            lane = int(row['Lane'])
            win = row.get(f'C{lane}_Win', 0)
            in2 = row.get(f'C{lane}_2in', 0)
            in3 = row.get(f'C{lane}_3in', 0)
            return pd.Series([win, in2, in3])
            
        df_prog[['Course_Win', 'Course_2in', 'Course_3in']] = df_prog.apply(get_lane_stats, axis=1)

    # 3. 出走表データを 1レース1行 にピボット
    print("出走表データをレースごとに横展開しています...")
    # カラムリストを動的に作成（Course_Win等を追加）
    pivot_cols = ['Rank', 'WinRate', 'Motor', 'Course_Win', 'Course_2in', 'Course_3in']
    pivot_prog = df_prog.pivot(index='ID', columns='Lane', values=pivot_cols)
    pivot_prog.columns = [f'B{lane}_{col}' for col, lane in pivot_prog.columns]
    pivot_prog = pivot_prog.reset_index()

    # 勝率などの数値化
    for lane in range(1, 7):
        pivot_prog[f'B{lane}_WinRate'] = pivot_prog[f'B{lane}_WinRate'].apply(clean_numeric)
        pivot_prog[f'B{lane}_RankScore'] = pivot_prog[f'B{lane}_Rank'].apply(rank_to_score)
        # コース別成績も数値化（念のため）
        for suffix in ['Win', '2in', '3in']:
            col = f'B{lane}_Course_{suffix}'
            if col in pivot_prog.columns:
                pivot_prog[col] = pd.to_numeric(pivot_prog[col], errors='coerce').fillna(0)

    # 4. 直前情報データ (df_info) のクレンジング
    print("直前情報データ（環境変数・展示タイムなど）をクレンジングしています...")
    # B1_ExTime などの展示タイムと、風速、波高を数値に
    env_cols = ['WindSpeed', 'Wave', 'WaterTemp']
    for c in env_cols:
        if c in df_info.columns:
            df_info[c] = df_info[c].apply(clean_numeric)

    for lane in range(1, 7):
        ex_col = f'B{lane}_ExTime'
        if ex_col in df_info.columns:
            df_info[ex_col] = df_info[ex_col].apply(clean_numeric)

    # 風向きのダミー変数化 (向かい風, 追い風, 左横風, 右横風, 無風)
    # WindDirをベースに後でワンホットエンコーディングするための準備
    df_info['WindDir'] = df_info['WindDir'].fillna('無風')

    # 4. 結果データ (df_res) からターゲット変数（正解ラベル）の作成
    print("結果データからターゲット変数を作成しています...")
    df_res['Target_1st'] = df_res['Result'].apply(extract_1st_place)
    df_res['Target_2nd'] = df_res['Result'].apply(extract_2nd_place)
    df_res['Target_3rd'] = df_res['Result'].apply(extract_3rd_place)

    # 5. すべてのデータをマージ（結合）
    print("全データを結合し、ml_features.csv を作成しています...")
    # df_info (ベース) + pivot_prog + df_res
    df_merged = pd.merge(df_info, pivot_prog, on='ID', how='inner')
    df_merged = pd.merge(df_merged, df_res[['ID', 'Result', 'Payout', 'Target_1st', 'Target_2nd', 'Target_3rd']], on='ID', how='inner')

    # 6. 新しい特徴量のエンジニアリング（独自指標の作成）
    # 例: 1号艇と2号艇の勝率差
    df_merged['Diff_WinRate_1_2'] = df_merged['B1_WinRate'] - df_merged['B2_WinRate']
    # 例: 1号艇と全平均勝率との差（実力の突出度）
    win_rates = [df_merged[f'B{i}_WinRate'] for i in range(1, 7)]
    df_merged['Avg_WinRate'] = np.nanmean(win_rates, axis=0)
    df_merged['B1_WinRate_Over_Avg'] = df_merged['B1_WinRate'] - df_merged['Avg_WinRate']

    # --- 追加特徴量 (2026-04 拡張) ---
    print("追加特徴量を生成しています...")

    # (A) 会場エンコーディング（Label Encoding）
    # 会場ごとに水面特性が全く違うため、カテゴリ特徴量として取り込む
    venue_list = sorted(df_merged['Venue'].dropna().unique())
    venue_to_id = {v: i for i, v in enumerate(venue_list)}
    df_merged['VenueID'] = df_merged['Venue'].map(venue_to_id).fillna(-1).astype(int)

    # (B) 月・季節の特徴量（水温・モーター性能に季節性がある）
    df_merged['Month'] = pd.to_datetime(df_merged['Date'], errors='coerce').dt.month.fillna(0).astype(int)

    # (C) 展示タイムの相対指標（1号艇が機力負けしているかの判定に重要）
    ex_times = []
    for lane in range(1, 7):
        col = f'B{lane}_ExTime'
        if col in df_merged.columns:
            ex_times.append(df_merged[col])
    if ex_times:
        ex_df = pd.concat(ex_times, axis=1)
        ex_df.columns = [f'B{i}_ExTime' for i in range(1, len(ex_times) + 1)]
        df_merged['ExTime_Min'] = ex_df.min(axis=1)          # 場内最速タイム
        df_merged['ExTime_Max'] = ex_df.max(axis=1)          # 場内最遅タイム
        df_merged['ExTime_Spread'] = df_merged['ExTime_Max'] - df_merged['ExTime_Min']  # タイム差（拮抗度）
        df_merged['B1_ExTime_vs_Min'] = df_merged['B1_ExTime'] - df_merged['ExTime_Min']  # 1号艇と最速の差
        df_merged['B1_ExTime_vs_Avg'] = df_merged['B1_ExTime'] - ex_df.mean(axis=1)       # 1号艇と平均の差

        # 展示タイム順位（1=最速）: 機力の序列を明示する
        ex_ranks = ex_df.rank(axis=1, method='min', ascending=True)
        for lane in range(1, 7):
            col = f'B{lane}_ExTime'
            if col in ex_df.columns:
                df_merged[f'B{lane}_ExTime_Rank'] = ex_ranks[col]

    # (D) 勝率の追加相対指標
    df_merged['Max_WinRate'] = pd.concat([df_merged[f'B{i}_WinRate'] for i in range(1, 7)], axis=1).max(axis=1)
    df_merged['WinRate_Spread'] = df_merged['Max_WinRate'] - pd.concat([df_merged[f'B{i}_WinRate'] for i in range(1, 7)], axis=1).min(axis=1)
    # 1号艇が最強かどうか（1号艇勝率 == 場内最高ならば1、そうでなければ差分の逆数的指標）
    df_merged['B1_Is_Top_WinRate'] = (df_merged['B1_WinRate'] >= df_merged['Max_WinRate']).astype(int)
    # 2-6号艇の最高勝率（1号艇の脅威度）
    outer_wr = pd.concat([df_merged[f'B{i}_WinRate'] for i in range(2, 7)], axis=1)
    df_merged['Max_Outer_WinRate'] = outer_wr.max(axis=1)
    df_merged['Diff_B1_vs_MaxOuter'] = df_merged['B1_WinRate'] - df_merged['Max_Outer_WinRate']

    # (E) ランクスコアの集約指標
    rank_scores = [df_merged[f'B{i}_RankScore'] for i in range(1, 7)]
    df_merged['Avg_RankScore'] = np.nanmean(rank_scores, axis=0)
    df_merged['B1_RankScore_Over_Avg'] = df_merged['B1_RankScore'] - df_merged['Avg_RankScore']

    # (F) 風向き × 風速の交互作用（向かい風で強風だとイン不利）
    # WindDir をカテゴリコードに変換
    wind_dir_map = {'追い風': 0, '向かい風': 1, '右横風': 2, '左横風': 3, '無風': 4}
    df_merged['WindDirCode'] = df_merged['WindDir'].map(wind_dir_map).fillna(4).astype(int)
    df_merged['IsHeadwind'] = (df_merged['WindDir'] == '向かい風').astype(int)
    df_merged['Headwind_x_Speed'] = df_merged['IsHeadwind'] * df_merged['WindSpeed'].fillna(0)

    print(f"  追加特徴量の生成完了。")

    # Phase 4: モーター成績の特徴量追加
    if use_db and not df_motor.empty:
        print("モーター成績の特徴量を追加しています...")
        # モーター成績辞書: (Venue, MotorNo) → {WinRate, Top2Rate, Top3Rate}
        motor_dict = {}
        for _, mrow in df_motor.iterrows():
            key = (str(mrow['Venue']), str(mrow['MotorNo']))
            motor_dict[key] = {
                'WinRate': float(mrow.get('WinRate', 0) or 0),
                'Top2Rate': float(mrow.get('Top2Rate', 0) or 0),
            }

        for lane in range(1, 7):
            motor_col = f'B{lane}_Motor'
            if motor_col in df_merged.columns:
                df_merged[f'B{lane}_MotorWinRate'] = df_merged.apply(
                    lambda row: motor_dict.get(
                        (str(row.get('Venue', '')), str(row.get(motor_col, ''))),
                        {}
                    ).get('WinRate', 0), axis=1
                )
                df_merged[f'B{lane}_Motor2inRate'] = df_merged.apply(
                    lambda row: motor_dict.get(
                        (str(row.get('Venue', '')), str(row.get(motor_col, ''))),
                        {}
                    ).get('Top2Rate', 0), axis=1
                )
        print(f"  モーター特徴量を {sum(1 for _ in motor_dict)} モーター分追加しました。")
    else:
        # モーターデータがない場合はゼロ埋め
        for lane in range(1, 7):
            df_merged[f'B{lane}_MotorWinRate'] = 0.0
            df_merged[f'B{lane}_Motor2inRate'] = 0.0

    # 保存
    df_merged.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
    print(f"完了！特徴量データセットを {OUTPUT_FILE} に保存しました。")
    print(f"総レース数（行数）: {len(df_merged)}行")

if __name__ == "__main__":
    main()
