"""Jリーグの試合日程・結果を J.League Data Site から収集する。

データ源: https://data.j-league.or.jp/SFMS01/search
  ?competition_years=<年> & competition_frame_ids=<1=J1,2=J2,3=J3>
  → サーバー側HTMLの試合一覧テーブル（pandas.read_html で解析可）

出力:
  - toto/data/jleague_matches.csv  （全リーグ・全年まとめ、1行=1試合）
  各行: season, league, matchday, date, kickoff, home, away,
        home_goals, away_goals, result(H/D/A or 空=未消化), stadium

使い方:
  python toto/collect_jleague.py            # 当年の J1/J2/J3 を収集
  python toto/collect_jleague.py 2023 2024 2025   # 指定年をバックフィル
"""
import os
import sys
import io
import re
import time
import datetime
import requests
import pandas as pd

# Windows cmd の cp932 stdout 対策（絵文字/日本語print）
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data")
OUT_CSV = os.path.join(OUT_DIR, "jleague_matches.csv")

BASE_URL = "https://data.j-league.or.jp/SFMS01/search"
FRAMES = {1: "J1", 2: "J2", 3: "J3"}   # competition_frame_ids → リーグ名
HEADERS = {"User-Agent": "Mozilla/5.0 (boatrace-toto data collector)"}

# サーバー側テーブルの列名（取得時の実際の日本語見出し）
COL_SEASON = "シーズン"
COL_LEAGUE = "大会"
COL_MATCHDAY = "節"
COL_DATE = "試合日"
COL_KICKOFF = "K/O時刻"
COL_HOME = "ホーム"
COL_SCORE = "スコア"
COL_AWAY = "アウェイ"
COL_STADIUM = "スタジアム"


def parse_date(s):
    """'25/02/14(金)' → '2025-02-14'。失敗時は元文字列。"""
    m = re.match(r"(\d{2})/(\d{2})/(\d{2})", str(s))
    if not m:
        return str(s)
    yy, mm, dd = m.groups()
    return f"20{yy}-{mm}-{dd}"


def parse_score(s):
    """'2-5' → (2, 5)。未消化('vs'/空/中止 等)は (None, None)。"""
    m = re.match(r"\s*(\d+)\s*-\s*(\d+)\s*", str(s))
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def to_result(hg, ag):
    """1X2: ホーム勝=H / 引分=D / アウェイ勝=A。未消化は空文字。"""
    if hg is None or ag is None:
        return ""
    if hg > ag:
        return "H"
    if hg < ag:
        return "A"
    return "D"


def fetch_season(year, frame_id):
    """指定年・リーグの試合一覧を DataFrame で返す（整形済み）。"""
    url = f"{BASE_URL}?competition_years={year}&competition_frame_ids={frame_id}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    # ヘッダにcharsetが無いと requests は ISO-8859-1 と誤推定するため明示補正
    r.encoding = r.apparent_encoding or "utf-8"

    tables = pd.read_html(io.StringIO(r.text))
    if not tables:
        return pd.DataFrame()
    df = tables[0]
    if COL_HOME not in df.columns or COL_SCORE not in df.columns:
        print(f"  [WARN] {year} {FRAMES[frame_id]}: 想定の列が見つからず (cols={list(df.columns)})")
        return pd.DataFrame()

    rows = []
    for _, x in df.iterrows():
        hg, ag = parse_score(x.get(COL_SCORE))
        rows.append({
            "season": str(x.get(COL_SEASON, year)).strip(),
            "league": FRAMES[frame_id],
            "matchday": str(x.get(COL_MATCHDAY, "")).strip(),
            "date": parse_date(x.get(COL_DATE)),
            "kickoff": str(x.get(COL_KICKOFF, "")).strip(),
            "home": str(x.get(COL_HOME, "")).strip(),
            "away": str(x.get(COL_AWAY, "")).strip(),
            "home_goals": hg,
            "away_goals": ag,
            "result": to_result(hg, ag),
            "stadium": str(x.get(COL_STADIUM, "")).strip(),
        })
    return pd.DataFrame(rows)


def collect(years, frame_ids=(1, 2, 3)):
    """複数年×複数リーグを収集して1本のDataFrameに。"""
    all_df = []
    for year in years:
        for fid in frame_ids:
            try:
                d = fetch_season(year, fid)
                n_done = (d["result"] != "").sum() if not d.empty else 0
                print(f"  {year} {FRAMES[fid]}: {len(d)}試合 (結果確定 {n_done})")
                if not d.empty:
                    all_df.append(d)
            except Exception as e:
                print(f"  [WARN] {year} {FRAMES[fid]} 取得失敗（スキップ）: {e}")
            time.sleep(1.0)  # サーバー負荷配慮
    if not all_df:
        return pd.DataFrame()
    return pd.concat(all_df, ignore_index=True)


def main():
    args = sys.argv[1:]
    if args:
        years = [int(a) for a in args]
    else:
        years = [datetime.date.today().year]

    print(f"=== Jリーグ収集: 対象年 {years} ===")
    df = collect(years)
    if df.empty:
        print("収集結果が空でした。")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    # 既存があればマージして重複排除（season+league+date+home+away をキー）
    if os.path.exists(OUT_CSV):
        old = pd.read_csv(OUT_CSV)
        df = pd.concat([old, df], ignore_index=True)
    key = ["season", "league", "date", "home", "away"]
    df = df.drop_duplicates(subset=key, keep="last").sort_values(["date", "kickoff"])
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n保存: {OUT_CSV} ({len(df)}試合)")


if __name__ == "__main__":
    main()
