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

def _compute_leak_safe_player_stats(df_prog, df_res):
    """各 (PlayerID, RaceID) について、そのレース日より厳密に前のデータだけで
    Career/Venue/VenueLane 系の集計値を計算する。

    旧実装(全期間集計)は時系列リークを生んでおり、val期間のレース時点で未来結果まで
    使った値を特徴量化していた。本関数は merge_asof + cumsum で「as of just before
    this race date」を厳密に計算する。

    Args:
        df_prog: 出走表テーブル。列: PlayerID, ID(=RaceID), Date, Venue, Lane, ...
        df_res:  結果テーブル。列: ID(=RaceID), Result(例 "1-2-3")

    Returns:
        DataFrame。列: PlayerID, ID, VenueWinRate, VenueRaceCount,
        VenueLanePWinRate, VenueLanePRaceCount, Career2inRate, Career3inRate
    """
    # 出走表 × 結果 を JOIN したイベント表
    events = df_prog[['PlayerID', 'ID', 'Date', 'Venue', 'Lane']].merge(
        df_res[['ID', 'Result']], on='ID', how='inner'
    )

    # Result "1-2-3" → 1着 / 2着 / 3着 lane を抽出
    parts = events['Result'].astype(str).str.split('-', expand=True)
    events['result_1st'] = pd.to_numeric(parts[0], errors='coerce')
    events['result_2nd'] = pd.to_numeric(parts[1], errors='coerce') if parts.shape[1] > 1 else np.nan
    events['result_3rd'] = pd.to_numeric(parts[2], errors='coerce') if parts.shape[1] > 2 else np.nan
    events = events.dropna(subset=['result_1st', 'result_2nd', 'result_3rd']).copy()

    events['Lane'] = events['Lane'].astype(int)
    events['result_1st'] = events['result_1st'].astype(int)
    events['result_2nd'] = events['result_2nd'].astype(int)
    events['result_3rd'] = events['result_3rd'].astype(int)

    events['was_1st'] = (events['Lane'] == events['result_1st']).astype(int)
    events['was_2nd'] = (events['Lane'] == events['result_2nd']).astype(int)
    events['was_3rd'] = (events['Lane'] == events['result_3rd']).astype(int)

    events['Date'] = pd.to_datetime(events['Date'])

    # === Career統計 (PlayerID×Date 単位で集約 → cumsum) ===
    daily_career = events.groupby(['PlayerID', 'Date'], sort=False).agg(
        races_today=('ID', 'size'),
        in2_today=('was_2nd', 'sum'),
        in3_today=('was_3rd', 'sum'),
    ).reset_index().sort_values(['PlayerID', 'Date'])
    grp = daily_career.groupby('PlayerID', sort=False)
    daily_career['career_cum_races'] = grp['races_today'].cumsum()
    daily_career['career_cum_in2']   = grp['in2_today'].cumsum()
    daily_career['career_cum_in3']   = grp['in3_today'].cumsum()

    # === Venue統計 (PlayerID×Venue×Date 単位) ===
    daily_venue = events.groupby(['PlayerID', 'Venue', 'Date'], sort=False).agg(
        races_today=('ID', 'size'),
        wins_today=('was_1st', 'sum'),
    ).reset_index().sort_values(['PlayerID', 'Venue', 'Date'])
    grp = daily_venue.groupby(['PlayerID', 'Venue'], sort=False)
    daily_venue['venue_cum_races'] = grp['races_today'].cumsum()
    daily_venue['venue_cum_wins']  = grp['wins_today'].cumsum()

    # === VenueLane統計 (PlayerID×Venue×Lane×Date 単位) ===
    daily_vl = events.groupby(['PlayerID', 'Venue', 'Lane', 'Date'], sort=False).agg(
        races_today=('ID', 'size'),
        wins_today=('was_1st', 'sum'),
    ).reset_index().sort_values(['PlayerID', 'Venue', 'Lane', 'Date'])
    grp = daily_vl.groupby(['PlayerID', 'Venue', 'Lane'], sort=False)
    daily_vl['vl_cum_races'] = grp['races_today'].cumsum()
    daily_vl['vl_cum_wins']  = grp['wins_today'].cumsum()

    # === df_prog の各行に「Date より厳密に前」の累積を merge_asof で付与 ===
    df_prog_dt = df_prog[['PlayerID', 'ID', 'Date', 'Venue', 'Lane']].copy()
    df_prog_dt['Date'] = pd.to_datetime(df_prog_dt['Date'])
    df_prog_dt['Lane'] = df_prog_dt['Lane'].astype(int)
    df_prog_dt = df_prog_dt.sort_values('Date').reset_index(drop=True)

    out = pd.merge_asof(
        df_prog_dt,
        daily_career[['PlayerID', 'Date', 'career_cum_races', 'career_cum_in2', 'career_cum_in3']].sort_values('Date'),
        on='Date', by='PlayerID',
        direction='backward', allow_exact_matches=False,
    )
    out = pd.merge_asof(
        out.sort_values('Date'),
        daily_venue[['PlayerID', 'Venue', 'Date', 'venue_cum_races', 'venue_cum_wins']].sort_values('Date'),
        on='Date', by=['PlayerID', 'Venue'],
        direction='backward', allow_exact_matches=False,
    )
    out = pd.merge_asof(
        out.sort_values('Date'),
        daily_vl[['PlayerID', 'Venue', 'Lane', 'Date', 'vl_cum_races', 'vl_cum_wins']].sort_values('Date'),
        on='Date', by=['PlayerID', 'Venue', 'Lane'],
        direction='backward', allow_exact_matches=False,
    )

    def safe_div(num, den):
        return (num / den.replace(0, np.nan)).fillna(0)

    out['Career2inRate']        = safe_div(out['career_cum_in2'].fillna(0), out['career_cum_races'].fillna(0))
    out['Career3inRate']        = safe_div(out['career_cum_in3'].fillna(0), out['career_cum_races'].fillna(0))
    out['VenueWinRate']         = safe_div(out['venue_cum_wins'].fillna(0), out['venue_cum_races'].fillna(0))
    out['VenueRaceCount']       = out['venue_cum_races'].fillna(0)
    out['VenueLanePWinRate']    = safe_div(out['vl_cum_wins'].fillna(0), out['vl_cum_races'].fillna(0))
    out['VenueLanePRaceCount']  = out['vl_cum_races'].fillna(0)

    return out[['PlayerID', 'ID',
                'VenueWinRate', 'VenueRaceCount',
                'VenueLanePWinRate', 'VenueLanePRaceCount',
                'Career2inRate', 'Career3inRate']]


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

    # 会場・キャリア系の特徴量をリーク無しで計算
    # （以前は races×results の全期間集計で未来結果を含んでいた → 時系列リーク）
    # 修正後: そのレース日より厳密に前のデータだけで as-of-prior-date 累積を計算
    if 'Result' in df_res.columns and not df_res.empty:
        try:
            stats_lf = _compute_leak_safe_player_stats(df_prog, df_res)
            df_prog = df_prog.merge(stats_lf, on=['PlayerID', 'ID'], how='left')
            # 統計が取れなかった行（最初期レース等）は妥当なフォールバック値で埋める
            df_prog['VenueWinRate']        = df_prog['VenueWinRate'].fillna(df_prog['WinRate'])
            df_prog['VenueRaceCount']      = df_prog['VenueRaceCount'].fillna(0)
            df_prog['VenueLanePWinRate']   = df_prog['VenueLanePWinRate'].fillna(df_prog['VenueWinRate'])
            df_prog['VenueLanePRaceCount'] = df_prog['VenueLanePRaceCount'].fillna(0)
            df_prog['Career2inRate']       = df_prog['Career2inRate'].fillna(0)
            df_prog['Career3inRate']       = df_prog['Career3inRate'].fillna(0)
        except Exception as e:
            print(f"[WARN] リーク無し集計に失敗: {e}. WinRate ベースのフォールバックを使用。")
            df_prog['VenueWinRate']        = df_prog['WinRate']
            df_prog['VenueRaceCount']      = 0
            df_prog['VenueLanePWinRate']   = df_prog['WinRate']
            df_prog['VenueLanePRaceCount'] = 0
            df_prog['Career2inRate']       = 0
            df_prog['Career3inRate']       = 0
    else:
        df_prog['VenueWinRate']        = df_prog['WinRate']
        df_prog['VenueRaceCount']      = 0
        df_prog['VenueLanePWinRate']   = df_prog['WinRate']
        df_prog['VenueLanePRaceCount'] = 0
        df_prog['Career2inRate']       = 0
        df_prog['Career3inRate']       = 0

    # 3. 出走表データを 1レース1行 にピボット
    print("出走表データをレースごとに横展開しています...")
    # カラムリストを動的に作成（Course_Win等を追加）
    pivot_extra = [c for c in ['VenueWinRate', 'VenueRaceCount', 'Career2inRate', 'Career3inRate', 'VenueLanePWinRate', 'VenueLanePRaceCount'] if c in df_prog.columns]
    pivot_cols = ['Rank', 'WinRate', 'Motor', 'Course_Win', 'Course_2in', 'Course_3in'] + pivot_extra
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
    # 循環エンコーディング: 12月→1月の不連続を埋めるため sin/cos 化
    df_merged['Month_Sin'] = np.sin(2 * np.pi * df_merged['Month'] / 12)
    df_merged['Month_Cos'] = np.cos(2 * np.pi * df_merged['Month'] / 12)

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
        # 1号艇と外艇(B2-B6)平均との差（自分を含まない外艇モーター平均との比較）
        outer_ex_cols = [f'B{i}_ExTime' for i in range(2, 7) if f'B{i}_ExTime' in ex_df.columns]
        if outer_ex_cols:
            df_merged['B1_ExTime_vs_AvgOuter'] = df_merged['B1_ExTime'] - ex_df[outer_ex_cols].mean(axis=1)

        # 展示タイム順位（1=最速）: 機力の序列を明示する
        ex_ranks = ex_df.rank(axis=1, method='min', ascending=True)
        for lane in range(1, 7):
            col = f'B{lane}_ExTime'
            if col in ex_df.columns:
                df_merged[f'B{lane}_ExTime_Rank'] = ex_ranks[col]

        # 全レーン展示タイム相対差: 各艇の展示タイムと場内最速/平均の差（連続値）
        ex_mean = ex_df.mean(axis=1)
        for lane in range(1, 7):
            col = f'B{lane}_ExTime'
            if col in ex_df.columns:
                df_merged[f'B{lane}_ExTime_vs_Min'] = df_merged[col] - df_merged['ExTime_Min']
                df_merged[f'B{lane}_ExTime_vs_Avg'] = df_merged[col] - ex_mean

    # (D) 勝率の追加相対指標
    wr_df = pd.concat([df_merged[f'B{i}_WinRate'] for i in range(1, 7)], axis=1)
    wr_df.columns = [f'B{i}_WinRate' for i in range(1, 7)]
    df_merged['Max_WinRate'] = wr_df.max(axis=1)
    df_merged['Race_Min_WinRate'] = wr_df.min(axis=1)  # レース内最低勝率（最弱艇シグナル）
    df_merged['WinRate_Spread'] = df_merged['Max_WinRate'] - df_merged['Race_Min_WinRate']
    # レース内最高キャリア2着率（2着争いの頂点シグナル、2nd model 補強）
    c2_cols = [f'B{i}_Career2inRate' for i in range(1, 7)]
    if all(c in df_merged.columns for c in c2_cols):
        c2_df = df_merged[c2_cols].astype(float)
        df_merged['Race_Max_Career2inRate'] = c2_df.max(axis=1)
        df_merged['Race_Min_Career2inRate'] = c2_df.min(axis=1)  # 最弱2着候補シグナル
        df_merged['Race_Median_Career2inRate'] = c2_df.median(axis=1)  # ロバストな中央値（min/max/avgとは異なる形状指標）
    # 勝率順位（1=最強）: 選手実力の序列を明示
    wr_ranks = wr_df.rank(axis=1, method='min', ascending=False)
    for lane in range(1, 7):
        df_merged[f'B{lane}_WinRate_Rank'] = wr_ranks[f'B{lane}_WinRate']
    # 1号艇が最強かどうか（1号艇勝率 == 場内最高ならば1、そうでなければ差分の逆数的指標）
    df_merged['B1_Is_Top_WinRate'] = (df_merged['B1_WinRate'] >= df_merged['Max_WinRate']).astype(int)
    # 2-6号艇の最高勝率（1号艇の脅威度）—— Diff_B1_vs_MaxOuter は除去（B1過信につながる可能性）
    outer_wr = pd.concat([df_merged[f'B{i}_WinRate'] for i in range(2, 7)], axis=1)
    df_merged['Max_Outer_WinRate'] = outer_wr.max(axis=1)
    # レース内の強豪艇数（WinRate > 6.0）: フィールドの強豪密度を示す離散特徴量
    # 多ければ「混戦レース」、少なければ「一強レース」
    df_merged['Race_N_StrongFavorites'] = sum(
        (df_merged[f'B{i}_WinRate'] > 6.0).fillna(False).astype(int) for i in range(1, 7)
    )
    # レース内の弱豪艇数（WinRate < 4.0）: 弱い艇が多い楽勝レースの指標
    # Race_N_StrongFavorites との鏡像的シグナル
    df_merged['Race_N_WeakBoats'] = sum(
        (df_merged[f'B{i}_WinRate'] < 4.0).fillna(False).astype(int) for i in range(1, 7)
    )
    # 極端に弱い艇の数（WinRate < 3.0）: より厳しい閾値の弱艇カウント
    df_merged['Race_N_VeryWeakBoats'] = sum(
        (df_merged[f'B{i}_WinRate'] < 3.0).fillna(False).astype(int) for i in range(1, 7)
    )
    # B2級（RankScore=1）の艇数: 公式階級ベースの最弱グレード密度
    df_merged['Race_N_BottomTier'] = sum(
        (df_merged[f'B{i}_RankScore'] == 1).fillna(False).astype(int) for i in range(1, 7)
    )
    # 二重弱艇（WR<3.0 AND B2級）の数: VeryWeakBoats と BottomTier の AND 条件 compound signal
    df_merged['Race_N_DoubleWeak'] = sum(
        ((df_merged[f'B{i}_WinRate'] < 3.0) & (df_merged[f'B{i}_RankScore'] == 1)).fillna(False).astype(int)
        for i in range(1, 7)
    )
    # 圧倒的本命フラグ: B1が最強 AND VeryWeakBoats が居る = 本命勝ちやすいレース
    df_merged['Race_HasUnanimousFavorite'] = (
        (df_merged['B1_Is_Top_WinRate'] == 1) & (df_merged['Race_N_VeryWeakBoats'] > 0)
    ).astype(int)
    # B1より勝率が高い外艇の数（B1脅威度の離散カウント 0-5）
    # Max_Outer_WinRate 連続値とは異なる「広がり」を表す
    b1_wr_ref = df_merged['B1_WinRate']
    df_merged['Race_N_OuterStrongerThanB1'] = sum(
        (df_merged[f'B{i}_WinRate'] > b1_wr_ref).fillna(False).astype(int) for i in range(2, 7)
    )

    # (E) ランクスコアの集約指標
    rank_scores = [df_merged[f'B{i}_RankScore'] for i in range(1, 7)]
    df_merged['Avg_RankScore'] = np.nanmean(rank_scores, axis=0)
    df_merged['B1_RankScore_Over_Avg'] = df_merged['B1_RankScore'] - df_merged['Avg_RankScore']
    # レース内最低RankScore（B2が居るかの強弱フラグ的シグナル、Max は破壊的だったが Min は独立情報）
    rs_df = pd.concat(rank_scores, axis=1)
    df_merged['Race_Min_RankScore'] = rs_df.min(axis=1)
    # B1ランクスコアと外艇平均との差（自己除外: B2-B6のみ平均）
    outer_rank_scores = [df_merged[f'B{i}_RankScore'] for i in range(2, 7)]
    df_merged['B1_RankScore_vs_AvgOuter'] = df_merged['B1_RankScore'] - np.nanmean(outer_rank_scores, axis=0)

    # B1チルトと外艇平均との差（自己除外パターンの Tilt 拡張）
    tilt_cols = [f'B{i}_Tilt' for i in range(1, 7)]
    if all(c in df_merged.columns for c in tilt_cols):
        b1_tilt_num = pd.to_numeric(df_merged['B1_Tilt'], errors='coerce')
        outer_tilt_num = pd.concat(
            [pd.to_numeric(df_merged[f'B{i}_Tilt'], errors='coerce') for i in range(2, 7)],
            axis=1,
        )
        df_merged['B1_Tilt_vs_AvgOuter'] = b1_tilt_num - outer_tilt_num.mean(axis=1)

    # (E4) コース別2着率の within-race 順位（2着争いの強さ順位）
    c2in_cols = [f'B{i}_Course_2in' for i in range(1, 7)]
    if all(c in df_merged.columns for c in c2in_cols):
        c2in_df = df_merged[c2in_cols].astype(float)
        c2in_ranks = c2in_df.rank(axis=1, method='min', ascending=False)
        for lane in range(1, 7):
            df_merged[f'B{lane}_Course_2in_Rank'] = c2in_ranks[f'B{lane}_Course_2in']

    # ExTimeMin_vs_VenueAvg（レース最速展示タイムと同会場平均との差）
    if 'ExTime_Min' in df_merged.columns and 'Venue' in df_merged.columns:
        venue_avg_exmin = df_merged.groupby('Venue')['ExTime_Min'].transform('mean')
        df_merged['ExTimeMin_vs_VenueAvg'] = df_merged['ExTime_Min'] - venue_avg_exmin

    # VenueLanePWinRate の within-race 順位（会場レーン適性順位）
    vlpwr_cols = [f'B{i}_VenueLanePWinRate' for i in range(1, 7)]
    if all(c in df_merged.columns for c in vlpwr_cols):
        vlpwr_df = df_merged[vlpwr_cols].apply(pd.to_numeric, errors='coerce')
        vlpwr_ranks = vlpwr_df.rank(axis=1, method='min', ascending=False)
        for lane in range(1, 7):
            df_merged[f'B{lane}_VenueLanePWR_Rank'] = vlpwr_ranks[f'B{lane}_VenueLanePWinRate']

    # VenueLanePWinRate × 展示タイム優位性（会場レーン適性 × 当日モーター速さ）
    for lane in range(1, 7):
        vlp_col = f'B{lane}_VenueLanePWinRate'
        etm_col = f'B{lane}_ExTime_vs_Min'
        if vlp_col in df_merged.columns and etm_col in df_merged.columns:
            vlp = pd.to_numeric(df_merged[vlp_col], errors='coerce').fillna(0)
            etm = pd.to_numeric(df_merged[etm_col], errors='coerce').fillna(0)
            df_merged[f'B{lane}_VenueLanePWR_x_ExAdv'] = vlp * (-etm)

    # VenueLanePWinRate × WinRate（会場レーン適性 × 総合勝率の複合）
    for lane in range(1, 7):
        vlp_col = f'B{lane}_VenueLanePWinRate'
        wr_col = f'B{lane}_WinRate'
        if vlp_col in df_merged.columns and wr_col in df_merged.columns:
            vlp = pd.to_numeric(df_merged[vlp_col], errors='coerce').fillna(0)
            wr = pd.to_numeric(df_merged[wr_col], errors='coerce').fillna(0)
            df_merged[f'B{lane}_VenueLanePWR_x_WR'] = vlp * wr

    # VenueLanePWinRateのベイズ平滑化（VenueWinRateを事前分布、alpha=5）
    # 高カウントは生の比率に近く、低カウントはVenueWinRateに引き寄せる
    alpha = 5.0
    for lane in range(1, 7):
        vlp_col = f'B{lane}_VenueLanePWinRate'
        vlpc_col = f'B{lane}_VenueLanePRaceCount'
        vwr_col = f'B{lane}_VenueWinRate'
        if all(c in df_merged.columns for c in [vlp_col, vlpc_col, vwr_col]):
            vlp = pd.to_numeric(df_merged[vlp_col], errors='coerce').fillna(0)
            cnt = pd.to_numeric(df_merged[vlpc_col], errors='coerce').fillna(0)
            vwr = pd.to_numeric(df_merged[vwr_col], errors='coerce').fillna(0)
            # Bayesian: (raw_wins + alpha*prior) / (count + alpha)
            # raw_wins = vlp * cnt
            df_merged[f'B{lane}_VenueLanePWR_Bayes'] = (vlp * cnt + alpha * vwr) / (cnt + alpha)

    # Course_Win × VenueLanePWR_Bayes（公式レーン勝率 × Bayesian平滑化済み会場レーン勝率の複合）
    for lane in range(1, 7):
        cw_col = f'B{lane}_Course_Win'
        bayes_col = f'B{lane}_VenueLanePWR_Bayes'
        if cw_col in df_merged.columns and bayes_col in df_merged.columns:
            cw = pd.to_numeric(df_merged[cw_col], errors='coerce').fillna(0)
            bayes = pd.to_numeric(df_merged[bayes_col], errors='coerce').fillna(0)
            df_merged[f'B{lane}_CourseWin_x_VLPBayes'] = cw * bayes

    # Course_Win × VenueWinRate（担当レーンの得意さ × 会場全体の得意さの複合）
    for lane in range(1, 7):
        cw_col = f'B{lane}_Course_Win'
        vwr_col = f'B{lane}_VenueWinRate'
        if cw_col in df_merged.columns and vwr_col in df_merged.columns:
            cw = pd.to_numeric(df_merged[cw_col], errors='coerce').fillna(0)
            vwr = pd.to_numeric(df_merged[vwr_col], errors='coerce').fillna(0)
            df_merged[f'B{lane}_CourseWin_x_VenueWR'] = cw * vwr

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
