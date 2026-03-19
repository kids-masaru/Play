import os
import pandas as pd
import numpy as np

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

def main():
    print("=== 特徴量エンジニアリング（学習データ作成）開始 ===")
    
    if not os.path.exists(PROG_FILE) or not os.path.exists(RES_FILE) or not os.path.exists(INFO_FILE):
        print("エラー: past_data フォルダに必要なCSVファイルが揃っていません。")
        return

    # 1. データ読み込み
    print("データを読み込んでいます...")
    df_prog = pd.read_csv(PROG_FILE)
    df_info = pd.read_csv(INFO_FILE)
    df_res  = pd.read_csv(RES_FILE)
    
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

    # 5. すべてのデータをマージ（結合）
    print("全データを結合し、ml_features.csv を作成しています...")
    # df_info (ベース) + pivot_prog + df_res
    df_merged = pd.merge(df_info, pivot_prog, on='ID', how='inner')
    df_merged = pd.merge(df_merged, df_res[['ID', 'Result', 'Payout', 'Target_1st']], on='ID', how='inner')

    # 6. 新しい特徴量のエンジニアリング（独自指標の作成）
    # 例: 1号艇と2号艇の勝率差
    df_merged['Diff_WinRate_1_2'] = df_merged['B1_WinRate'] - df_merged['B2_WinRate']
    # 例: 1号艇と全平均勝率との差（実力の突出度）
    win_rates = [df_merged[f'B{i}_WinRate'] for i in range(1, 7)]
    df_merged['Avg_WinRate'] = np.nanmean(win_rates, axis=0)
    df_merged['B1_WinRate_Over_Avg'] = df_merged['B1_WinRate'] - df_merged['Avg_WinRate']

    # 保存
    df_merged.to_csv(OUTPUT_FILE, index=False, encoding='utf-8')
    print(f"完了！特徴量データセットを {OUTPUT_FILE} に保存しました。")
    print(f"総レース数（行数）: {len(df_merged)}行")

if __name__ == "__main__":
    main()
