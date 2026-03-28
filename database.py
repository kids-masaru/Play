"""
Phase 4: SQLiteデータベース層
全CSVデータをSQLiteに統合し、高速な読み書きと条件検索を提供する。
"""
import os
import sqlite3
import pandas as pd
import numpy as np
from contextlib import contextmanager

# --- 設定 ---
DB_DIR = "data"
DB_FILE = os.path.join(DB_DIR, "boatrace.db")


@contextmanager
def get_connection():
    """SQLite接続のコンテキストマネージャ"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL")       # 並行読み取り性能向上
    conn.execute("PRAGMA synchronous=NORMAL")      # 書き込み性能向上
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =========================================================
# スキーマ定義
# =========================================================
SCHEMA_SQL = """
-- 出走表 (past_race_data / daily_raw_race_data)
CREATE TABLE IF NOT EXISTS races (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Date        TEXT NOT NULL,
    Venue       TEXT NOT NULL,
    R           INTEGER NOT NULL,
    RaceID      TEXT NOT NULL,
    Lane        INTEGER NOT NULL,
    PlayerID    TEXT,
    Name        TEXT,
    Motor       TEXT,
    Rank        TEXT,
    WinRate     TEXT,
    Count       TEXT,
    UNIQUE(RaceID, Lane)
);

-- 結果 (past_history_results / daily_history_results)
CREATE TABLE IF NOT EXISTS results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Date        TEXT NOT NULL,
    Venue       TEXT NOT NULL,
    R           INTEGER NOT NULL,
    RaceID      TEXT NOT NULL UNIQUE,
    Result      TEXT,
    Payout      TEXT
);

-- 直前情報 (past_raw_beforeinfo / daily_raw_beforeinfo)
CREATE TABLE IF NOT EXISTS beforeinfo (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    RaceID      TEXT NOT NULL UNIQUE,
    Date        TEXT NOT NULL,
    Venue       TEXT NOT NULL,
    R           INTEGER NOT NULL,
    Weather     TEXT,
    WindSpeed   TEXT,
    WindDir     TEXT,
    Wave        TEXT,
    WaterTemp   TEXT,
    B1_Weight   TEXT, B1_Tilt TEXT, B1_ExTime TEXT,
    B2_Weight   TEXT, B2_Tilt TEXT, B2_ExTime TEXT,
    B3_Weight   TEXT, B3_Tilt TEXT, B3_ExTime TEXT,
    B4_Weight   TEXT, B4_Tilt TEXT, B4_ExTime TEXT,
    B5_Weight   TEXT, B5_Tilt TEXT, B5_ExTime TEXT,
    B6_Weight   TEXT, B6_Tilt TEXT, B6_ExTime TEXT
);

-- オッズ (past_odds_3t / daily_odds_3t)
CREATE TABLE IF NOT EXISTS odds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    RaceID      TEXT NOT NULL,
    Date        TEXT NOT NULL,
    Venue       TEXT NOT NULL,
    R           INTEGER NOT NULL,
    Combination TEXT NOT NULL,
    Odds        REAL,
    UNIQUE(RaceID, Combination)
);

-- 選手コース別成績
CREATE TABLE IF NOT EXISTS player_stats (
    PlayerID    TEXT PRIMARY KEY,
    C1_Win REAL, C1_2in REAL, C1_3in REAL,
    C2_Win REAL, C2_2in REAL, C2_3in REAL,
    C3_Win REAL, C3_2in REAL, C3_3in REAL,
    C4_Win REAL, C4_2in REAL, C4_3in REAL,
    C5_Win REAL, C5_2in REAL, C5_3in REAL,
    C6_Win REAL, C6_2in REAL, C6_3in REAL
);

-- AI予測
CREATE TABLE IF NOT EXISTS predictions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    RaceID      TEXT NOT NULL UNIQUE,
    Date        TEXT,
    Venue       TEXT,
    R           INTEGER,
    Prediction  TEXT,
    Log         TEXT
);

-- 反省（教訓）
CREATE TABLE IF NOT EXISTS reflections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    RaceID      TEXT NOT NULL UNIQUE,
    Date        TEXT,
    Venue       TEXT,
    Weather     TEXT,
    WindLevel   TEXT,
    Lesson      TEXT
);

-- モーター成績 (Phase 4 新規)
CREATE TABLE IF NOT EXISTS motor_stats (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    Venue       TEXT NOT NULL,
    MotorNo     TEXT NOT NULL,
    WinRate     REAL,
    Top2Rate    REAL,
    Top3Rate    REAL,
    UpdatedDate TEXT,
    UNIQUE(Venue, MotorNo)
);

-- インデックス
CREATE INDEX IF NOT EXISTS idx_races_date ON races(Date);
CREATE INDEX IF NOT EXISTS idx_races_raceid ON races(RaceID);
CREATE INDEX IF NOT EXISTS idx_results_date ON results(Date);
CREATE INDEX IF NOT EXISTS idx_results_raceid ON results(RaceID);
CREATE INDEX IF NOT EXISTS idx_beforeinfo_raceid ON beforeinfo(RaceID);
CREATE INDEX IF NOT EXISTS idx_odds_raceid ON odds(RaceID);
CREATE INDEX IF NOT EXISTS idx_odds_date ON odds(Date);
CREATE INDEX IF NOT EXISTS idx_predictions_date ON predictions(Date);
CREATE INDEX IF NOT EXISTS idx_reflections_date ON reflections(Date);
CREATE INDEX IF NOT EXISTS idx_motor_stats_venue ON motor_stats(Venue);
"""


def init_db():
    """データベースとテーブルを初期化する"""
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
    print(f"  ✅ データベースを初期化しました: {DB_FILE}")


# =========================================================
# 汎用 INSERT / QUERY
# =========================================================
def insert_rows(table, columns, rows, on_conflict="IGNORE"):
    """複数行を一括INSERTする

    Args:
        table: テーブル名
        columns: カラム名のリスト
        rows: データ行のリスト（リストのリスト）
        on_conflict: "IGNORE" (重複スキップ) or "REPLACE" (上書き)
    """
    if not rows:
        return 0

    placeholders = ", ".join(["?"] * len(columns))
    col_str = ", ".join(columns)
    sql = f"INSERT OR {on_conflict} INTO {table} ({col_str}) VALUES ({placeholders})"

    with get_connection() as conn:
        conn.executemany(sql, rows)
        return conn.total_changes


def query_df(sql, params=None):
    """SQLクエリを実行してDataFrameで返す"""
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params or [])


def query_one(sql, params=None):
    """1行だけ取得する"""
    with get_connection() as conn:
        cur = conn.execute(sql, params or [])
        row = cur.fetchone()
        return dict(row) if row else None


def execute(sql, params=None):
    """任意のSQL文を実行する"""
    with get_connection() as conn:
        conn.execute(sql, params or [])


# =========================================================
# テーブル別 CRUD 関数
# =========================================================

# --- races ---
RACE_COLUMNS = ["Date", "Venue", "R", "RaceID", "Lane", "PlayerID", "Name", "Motor", "Rank", "WinRate", "Count"]

def insert_races(rows):
    """出走表データを挿入する。rows = list of list（CSVのrow形式に対応）"""
    # CSV形式: [Date, Venue, R, ID, Lane, PlayerID, Name, Motor, Rank, WinRate, Count]
    return insert_rows("races", RACE_COLUMNS, rows)

def get_races_by_date(date_str):
    """指定日の出走表をDataFrameで返す"""
    return query_df("SELECT * FROM races WHERE Date = ?", [date_str])

def get_race_ids_by_date(date_str):
    """指定日のRaceIDリストを返す"""
    df = query_df("SELECT DISTINCT RaceID FROM races WHERE Date = ?", [date_str])
    return set(df['RaceID'].astype(str).values)

def get_venues_by_date(date_str):
    """指定日の会場リストを返す"""
    df = query_df("SELECT DISTINCT Venue FROM races WHERE Date = ?", [date_str])
    return set(df['Venue'].values)


# --- results ---
RESULT_COLUMNS = ["Date", "Venue", "R", "RaceID", "Result", "Payout"]

def insert_results(rows):
    return insert_rows("results", RESULT_COLUMNS, rows)

def get_results_by_date(date_str):
    return query_df("SELECT * FROM results WHERE Date = ?", [date_str])

def get_result_by_race_id(race_id):
    return query_one("SELECT * FROM results WHERE RaceID = ?", [race_id])


# --- beforeinfo ---
BEFOREINFO_COLUMNS = [
    "RaceID", "Date", "Venue", "R", "Weather", "WindSpeed", "WindDir", "Wave", "WaterTemp",
    "B1_Weight", "B1_Tilt", "B1_ExTime", "B2_Weight", "B2_Tilt", "B2_ExTime",
    "B3_Weight", "B3_Tilt", "B3_ExTime", "B4_Weight", "B4_Tilt", "B4_ExTime",
    "B5_Weight", "B5_Tilt", "B5_ExTime", "B6_Weight", "B6_Tilt", "B6_ExTime"
]

def insert_beforeinfo(rows):
    return insert_rows("beforeinfo", BEFOREINFO_COLUMNS, rows)

def get_beforeinfo_by_date(date_str):
    return query_df("SELECT * FROM beforeinfo WHERE Date = ?", [date_str])

def get_beforeinfo_by_race_id(race_id):
    return query_one("SELECT * FROM beforeinfo WHERE RaceID = ?", [race_id])


# --- odds ---
ODDS_COLUMNS = ["RaceID", "Date", "Venue", "R", "Combination", "Odds"]

def insert_odds(rows):
    return insert_rows("odds", ODDS_COLUMNS, rows)

def get_odds_by_date(date_str):
    return query_df("SELECT * FROM odds WHERE Date = ?", [date_str])

def get_odds_by_race_id(race_id):
    return query_df("SELECT * FROM odds WHERE RaceID = ?", [race_id])


# --- player_stats ---
PLAYER_STATS_COLUMNS = [
    "PlayerID", "C1_Win", "C1_2in", "C1_3in", "C2_Win", "C2_2in", "C2_3in",
    "C3_Win", "C3_2in", "C3_3in", "C4_Win", "C4_2in", "C4_3in",
    "C5_Win", "C5_2in", "C5_3in", "C6_Win", "C6_2in", "C6_3in"
]

def insert_player_stats(rows):
    return insert_rows("player_stats", PLAYER_STATS_COLUMNS, rows, on_conflict="REPLACE")

def get_player_stats(player_id):
    return query_one("SELECT * FROM player_stats WHERE PlayerID = ?", [str(player_id)])

def get_all_player_stats():
    return query_df("SELECT * FROM player_stats")

def get_existing_player_ids():
    df = query_df("SELECT PlayerID FROM player_stats")
    return set(df['PlayerID'].astype(str).values)


# --- predictions ---
PREDICTION_COLUMNS = ["RaceID", "Date", "Venue", "R", "Prediction", "Log"]

def insert_prediction(race_id, date, venue, r, prediction, log):
    insert_rows("predictions", PREDICTION_COLUMNS,
                [[race_id, date, venue, r, prediction, log]], on_conflict="REPLACE")

def get_predictions_by_date(date_str):
    return query_df("SELECT * FROM predictions WHERE Date = ?", [date_str])

def get_predicted_race_ids():
    df = query_df("SELECT RaceID FROM predictions")
    return set(df['RaceID'].astype(str).values)

def get_all_predictions():
    return query_df("SELECT * FROM predictions ORDER BY Date DESC")

def delete_prediction(race_id):
    execute("DELETE FROM predictions WHERE RaceID = ?", [race_id])


# --- reflections ---
REFLECTION_COLUMNS = ["RaceID", "Date", "Venue", "Weather", "WindLevel", "Lesson"]

def insert_reflection(race_id, date, venue, weather, wind_level, lesson):
    insert_rows("reflections", REFLECTION_COLUMNS,
                [[race_id, date, venue, weather, wind_level, lesson]], on_conflict="REPLACE")

def get_reflected_race_ids():
    df = query_df("SELECT RaceID FROM reflections")
    return set(df['RaceID'].astype(str).values)

def get_relevant_reflections(venue=None, weather=None, wind_level=None, max_count=5):
    """条件に合致する教訓をスコアリングして返す（Phase 3対応）"""
    df = query_df("SELECT * FROM reflections ORDER BY Date DESC LIMIT 200")
    if df.empty:
        return []

    scored = []
    for _, row in df.iterrows():
        text = str(row.get('Lesson', ''))
        if '教訓' not in text:
            continue

        cleaned = text.replace('\n', ' ').strip()[:150]
        score = 0

        if venue and str(row.get('Venue', '')) == venue:
            score += 3
        if weather and str(row.get('Weather', '')) == weather:
            score += 2
        if wind_level and str(row.get('WindLevel', '')) == wind_level:
            score += 1

        scored.append((score, cleaned, str(row.get('Date', ''))))

    scored.sort(key=lambda x: (x[0], x[2]), reverse=True)
    return [text for _, text, _ in scored[:max_count]]


# --- motor_stats ---
MOTOR_STATS_COLUMNS = ["Venue", "MotorNo", "WinRate", "Top2Rate", "Top3Rate", "UpdatedDate"]

def insert_motor_stats(rows):
    return insert_rows("motor_stats", MOTOR_STATS_COLUMNS, rows, on_conflict="REPLACE")

def get_motor_stats(venue, motor_no):
    return query_one(
        "SELECT * FROM motor_stats WHERE Venue = ? AND MotorNo = ?",
        [venue, str(motor_no)]
    )

def get_motor_stats_by_venue(venue):
    return query_df("SELECT * FROM motor_stats WHERE Venue = ?", [venue])


# =========================================================
# CSVマイグレーション
# =========================================================
def migrate_csv_to_db():
    """既存のCSVデータをSQLiteにマイグレーションする"""
    print("=== CSV → SQLite マイグレーション開始 ===")
    init_db()

    # --- past_data ---
    _migrate_csv("past_data/past_race_data.csv", "races", RACE_COLUMNS,
                 csv_col_map={"ID": "RaceID"})
    _migrate_csv("past_data/past_history_results.csv", "results", RESULT_COLUMNS,
                 csv_col_map={"ID": "RaceID"})
    _migrate_csv("past_data/past_raw_beforeinfo.csv", "beforeinfo", BEFOREINFO_COLUMNS,
                 csv_col_map={"ID": "RaceID"})

    if os.path.exists("past_data/past_player_course_stats.csv"):
        _migrate_csv("past_data/past_player_course_stats.csv", "player_stats", PLAYER_STATS_COLUMNS)

    if os.path.exists("past_data/past_odds_3t.csv"):
        _migrate_csv("past_data/past_odds_3t.csv", "odds", ODDS_COLUMNS,
                     csv_col_map={"ID": "RaceID"})

    # --- daily_data ---
    _migrate_csv("daily_data/daily_raw_race_data.csv", "races", RACE_COLUMNS,
                 csv_col_map={"ID": "RaceID"})
    _migrate_csv("daily_data/daily_history_results.csv", "results", RESULT_COLUMNS,
                 csv_col_map={"ID": "RaceID"})
    _migrate_csv("daily_data/daily_raw_beforeinfo.csv", "beforeinfo", BEFOREINFO_COLUMNS,
                 csv_col_map={"ID": "RaceID"})

    if os.path.exists("daily_data/daily_player_course_stats.csv"):
        _migrate_csv("daily_data/daily_player_course_stats.csv", "player_stats", PLAYER_STATS_COLUMNS)

    if os.path.exists("daily_data/daily_odds_3t.csv"):
        _migrate_csv("daily_data/daily_odds_3t.csv", "odds", ODDS_COLUMNS,
                     csv_col_map={"ID": "RaceID"})

    if os.path.exists("daily_data/daily_predictions.csv"):
        _migrate_csv("daily_data/daily_predictions.csv", "predictions", PREDICTION_COLUMNS,
                     csv_col_map={"RaceID": "RaceID"})

    if os.path.exists("daily_data/daily_reflections.csv"):
        _migrate_reflections("daily_data/daily_reflections.csv")

    # 統計表示
    _print_db_stats()
    print("=== マイグレーション完了 ===")


def _migrate_csv(csv_path, table, columns, csv_col_map=None):
    """CSVファイルをDBテーブルにインポートする"""
    if not os.path.exists(csv_path):
        print(f"  [SKIP] {csv_path} が見つかりません")
        return

    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception as e:
        print(f"  [ERROR] {csv_path} 読み込み失敗: {e}")
        return

    if df.empty:
        print(f"  [SKIP] {csv_path} は空です")
        return

    # カラム名リマップ（CSV上の "ID" → DB上の "RaceID" など）
    if csv_col_map:
        df = df.rename(columns=csv_col_map)

    # DBカラムに合わせてデータを整形
    available_cols = [c for c in columns if c in df.columns]
    missing_cols = [c for c in columns if c not in df.columns]

    if missing_cols:
        for mc in missing_cols:
            df[mc] = ''
        available_cols = columns

    df_insert = df[columns].fillna('')
    rows = df_insert.values.tolist()

    count = insert_rows(table, columns, rows)
    print(f"  ✅ {csv_path} → {table}: {len(rows)} 行読み込み")


def _migrate_reflections(csv_path):
    """反省データの移行（Venue/Weather/WindLevel カラムの有無を考慮）"""
    if not os.path.exists(csv_path):
        return

    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception:
        return

    if df.empty:
        return

    for col in ['Venue', 'Weather', 'WindLevel']:
        if col not in df.columns:
            df[col] = ''

    df = df.fillna('')
    rows = df[REFLECTION_COLUMNS].values.tolist()
    insert_rows("reflections", REFLECTION_COLUMNS, rows)
    print(f"  ✅ {csv_path} → reflections: {len(rows)} 行読み込み")


def _print_db_stats():
    """DB内の各テーブルのレコード数を表示する"""
    tables = ["races", "results", "beforeinfo", "odds", "player_stats",
              "predictions", "reflections", "motor_stats"]
    print("\n  📊 データベース統計:")
    with get_connection() as conn:
        for t in tables:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM {t}")
                count = cur.fetchone()[0]
                print(f"    {t}: {count:,} 件")
            except Exception:
                print(f"    {t}: (テーブルなし)")


# =========================================================
# ユーティリティ
# =========================================================
def db_exists():
    """DBファイルが存在するかチェック"""
    return os.path.exists(DB_FILE)


def ensure_db():
    """DBが未初期化ならセットアップする"""
    if not db_exists():
        init_db()


# =========================================================
# スタンドアロン実行: マイグレーション
# =========================================================
if __name__ == "__main__":
    migrate_csv_to_db()
