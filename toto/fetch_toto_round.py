"""toto公式から「販売中の回号・対象試合・投票締切」を取得する。(F2 / T3)

データ源:
  1) 候補回号の一覧（軽量・静的HTML）
       https://toto.yahoo.co.jp/schedule/toto
       → 本文中の「第NNNN回」を正規表現で抽出（回号 == 公式 holdCntId）
  2) 各回の詳細（試合一覧・販売日程・締切。pandas.read_html で解析可）
       https://store.toto-dream.com/.../PGSPIN00001DisptotoLotInfo.form?holdCntId=<回号>
       → くじ種別ごと（toto / mini toto-A組 / mini toto-B組 / totoGOAL3）に
         「タイトル → 販売日程 → 試合一覧(N×7) → 売上 → 払戻」の表が並ぶ

出力:
  toto/data/round_<回号>.json   現在販売中の各回を1ファイル
  各 JSON: round, fetched_date, kuji{ toto, mini_a, mini_b, goal3 }
    各 kuji: sale_start, deadline(ネット決済締切), result_date, matches[]
    各 match: no, date, kickoff, stadium, home, away

使い方:
  python toto/fetch_toto_round.py            # 販売中の回を自動検知して保存
  python toto/fetch_toto_round.py 1635       # 回号を指定して取得（販売状況に依らず）

備考:
  - 国際試合の回（Jリーグ off 期等）は home/away が代表名になる。
    その場合でも対象試合と締切は取得できる（統計予測のスキップは後段で判断）。
"""
import os
import sys
import io
import re
import json
import datetime
import requests
import pandas as pd

# Windows cmd の cp932 stdout 対策（日本語 print の文字化け/例外回避）
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "data")

YAHOO_SCHEDULE = "https://toto.yahoo.co.jp/schedule/toto"
DETAIL_URL = ("https://store.toto-dream.com/dcs/subos/screen/pi01/spin000/"
              "PGSPIN00001DisptotoLotInfo.form?holdCntId={rid}")
HEADERS = {"User-Agent": "Mozilla/5.0 (boatrace-toto round fetcher)"}

# 詳細ページのくじ種別タイトル → 出力キー。
# 注意: 'totoGOAL3' は 'toto' を含むため、長い名前から先に判定すること。
KUJI_PATTERNS = [
    ("goal3", "totoGOAL3"),
    ("mini_a", "mini toto-A組"),
    ("mini_b", "mini toto-B組"),
    ("toto", "toto"),
]

# 試合一覧テーブルの見出し（実際の取得時の日本語）
COL_NO = "Unnamed: 0"
COL_DATE = "開催日"
COL_KICKOFF = "試合開始 予定時間"
COL_STADIUM = "競技場"
COL_HOME = "指定試合（ホームvsアウェイ）"        # ホーム
COL_AWAY = "指定試合（ホームvsアウェイ）.2"      # アウェイ（.1 は "VS"）


def get(url):
    """UTF-8 固定でHTML本文を取得（toto/Yahoo とも meta charset=UTF-8）。"""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    return r.text


def list_candidate_rounds():
    """Yahoo スケジュールから候補回号（昇順 int リスト）を返す。失敗時は空。"""
    try:
        html = get(YAHOO_SCHEDULE)
    except Exception as e:
        print(f"  [WARN] Yahoo スケジュール取得失敗: {e}")
        return []
    rounds = {int(x) for x in re.findall(r"第(\d{3,4})回", html)}
    return sorted(rounds)


def parse_ja_date(s):
    """'2026年06月16日（火）...' → datetime.date。失敗時 None。"""
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", str(s))
    if not m:
        return None
    return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def parse_sale_start(s):
    """'2026年06月09日（火）08：00' → 'YYYY-MM-DD HH:MM'。全角コロンにも対応。"""
    d = parse_ja_date(s)
    if d is None:
        return ""
    tm = re.search(r"日（.）\s*(\d{1,2})[：:](\d{2})", str(s))
    hm = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "00:00"
    return f"{d.isoformat()} {hm}"


def parse_deadline(s):
    """販売終了日セルからネット決済の投票締切を返す。
    例: '2026年06月16日（火）（当サイト(ネット決済) 19:00／...）'
        → '2026-06-16 19:00'。時刻が拾えなければ 19:00 を既定とする。
    """
    d = parse_ja_date(s)
    if d is None:
        return ""
    tm = re.search(r"ネット決済\)?\s*(\d{1,2}):(\d{2})", str(s))
    hm = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else "19:00"
    return f"{d.isoformat()} {hm}"


def infer_match_date(md_str, base_year, base_month):
    """'06/17' に年を補う。販売開始の年月を基準に、月が戻る場合は翌年扱い
    （12月販売→1月開催の年跨ぎ対策）。失敗時は元文字列。"""
    m = re.match(r"(\d{1,2})/(\d{1,2})", str(md_str))
    if not m:
        return str(md_str).strip()
    mm, dd = int(m.group(1)), int(m.group(2))
    year = base_year + 1 if (base_month and mm < base_month - 6) else base_year
    return f"{year}-{mm:02d}-{dd:02d}"


def _kuji_key(title_text):
    """タイトル文字列からくじ種別キーを判定。該当なしは None。"""
    for key, label in KUJI_PATTERNS:
        if label in title_text:
            return key
    return None


def parse_detail(rid):
    """指定回号の詳細を解析して dict を返す。販売されていない回は None。"""
    html = get(DETAIL_URL.format(rid=rid))
    if "指定試合" not in html:
        return None  # 未販売 / 存在しない回（試合表が無い）

    tables = pd.read_html(io.StringIO(html))
    kuji = {}
    cur = None  # 現在処理中のくじ種別キー

    for t in tables:
        cols = [str(c) for c in t.columns]

        # 1) 試合一覧テーブル（最優先で判定）
        if COL_HOME in cols and COL_DATE in cols:
            if cur is None:
                continue
            sec = kuji.setdefault(cur, {})
            base = sec.get("_sale_start_date")
            by = base.year if base else datetime.date.today().year
            bm = base.month if base else 0
            matches = []
            for _, x in t.iterrows():
                home = str(x.get(COL_HOME, "")).strip()
                away = str(x.get(COL_AWAY, "")).strip()
                if not home or home.lower() == "nan":
                    continue
                matches.append({
                    "no": str(x.get(COL_NO, "")).strip(),
                    "date": infer_match_date(x.get(COL_DATE), by, bm),
                    "kickoff": str(x.get(COL_KICKOFF, "")).strip(),
                    "stadium": str(x.get(COL_STADIUM, "")).strip(),
                    "home": home,
                    "away": away,
                })
            sec["matches"] = matches
            continue

        # セル全体を1つの文字列にして種別やキーワードを探索
        flat = " ".join(str(v) for v in t.values.ravel() if pd.notna(v))

        # 2) くじ種別タイトル（'… くじ情報'）
        if "くじ情報" in flat:
            k = _kuji_key(flat)
            if k:
                cur = k
                kuji.setdefault(cur, {})
            continue

        # 3) 販売日程テーブル（販売開始日 / 販売終了日 / 結果発表日）
        if "販売終了日" in flat and cur is not None:
            sec = kuji.setdefault(cur, {})
            col0 = {str(r[0]).strip(): str(r[1]).strip() for r in t.values
                    if len(r) >= 2 and pd.notna(r[0])}
            sec["sale_start"] = parse_sale_start(col0.get("販売開始日", ""))
            sec["deadline"] = parse_deadline(col0.get("販売終了日", ""))
            d = parse_ja_date(col0.get("結果発表日", ""))
            sec["result_date"] = d.isoformat() if d else ""
            sd = parse_ja_date(col0.get("販売開始日", ""))
            ed = parse_ja_date(col0.get("販売終了日", ""))
            sec["_sale_start_date"] = sd
            sec["_sale_end_date"] = ed
            continue

    if not kuji:
        return None
    return {"round": rid, "kuji": kuji}


def sale_window(detail):
    """回全体の販売期間 (start_date, end_date) を toto を優先に返す。"""
    order = ["toto", "mini_a", "mini_b", "goal3"]
    for k in order:
        sec = detail["kuji"].get(k)
        if sec and sec.get("_sale_start_date") and sec.get("_sale_end_date"):
            return sec["_sale_start_date"], sec["_sale_end_date"]
    return None, None


def clean_for_json(detail, today):
    """内部用 _sale_*_date を除いて整形し、メタ情報を付与して返す。"""
    out = {"round": detail["round"], "fetched_date": today.isoformat(), "kuji": {}}
    for k, sec in detail["kuji"].items():
        out["kuji"][k] = {
            "sale_start": sec.get("sale_start", ""),
            "deadline": sec.get("deadline", ""),
            "result_date": sec.get("result_date", ""),
            "matches": sec.get("matches", []),
        }
    return out


def save_round(detail, today):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"round_{detail['round']}.json")
    data = clean_for_json(detail, today)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path, data


def summarize(data):
    """1回分の概要を見やすく print。"""
    print(f"  第{data['round']}回:")
    for k in ["toto", "mini_a", "mini_b", "goal3"]:
        sec = data["kuji"].get(k)
        if not sec:
            continue
        ms = sec.get("matches", [])
        print(f"    [{k}] 試合{len(ms)} / 締切 {sec.get('deadline','?')}")
        for m in ms[:3]:
            print(f"        {m['no']}. {m['date']} {m['kickoff']} "
                  f"{m['home']} vs {m['away']}")
        if len(ms) > 3:
            print(f"        ... 他 {len(ms)-3} 試合")


def discover_and_save(today):
    """販売中の回を自動検知して保存。販売中が無ければ直近の予定回を案内。"""
    cands = list_candidate_rounds()
    if not cands:
        print("候補回号が取得できませんでした（Yahoo スケジュール）。")
        return []
    # 直近 6 回のみ詳細確認（古い回の無駄打ちを避ける）
    probe = [r for r in cands if r >= max(cands) - 5]
    print(f"候補回号(直近): {probe}")

    on_sale, upcoming = [], []
    for rid in sorted(probe, reverse=True):
        try:
            detail = parse_detail(rid)
        except Exception as e:
            print(f"  [WARN] 第{rid}回 取得失敗（スキップ）: {e}")
            continue
        if detail is None:
            continue
        sd, ed = sale_window(detail)
        if sd and ed and sd <= today <= ed:
            on_sale.append(detail)
        elif sd and today < sd:
            upcoming.append((sd, detail))

    saved = []
    if on_sale:
        print(f"\n=== 販売中の回: {[d['round'] for d in on_sale]} ===")
        for detail in on_sale:
            path, data = save_round(detail, today)
            summarize(data)
            print(f"    → 保存: {path}")
            saved.append(data)
    else:
        print("\n現在販売中の回はありません。")
        if upcoming:
            upcoming.sort(key=lambda x: x[0])
            sd, nxt = upcoming[0]
            print(f"（直近の予定: 第{nxt['round']}回 販売開始 {sd.isoformat()}）")
    return saved


def main():
    today = datetime.date.today()
    args = sys.argv[1:]
    print(f"=== toto回号取得 (基準日 {today.isoformat()}) ===")

    if args:
        # 回号を明示指定（販売状況に依らず取得）
        for a in args:
            rid = int(a)
            try:
                detail = parse_detail(rid)
            except Exception as e:
                print(f"第{rid}回 取得失敗: {e}")
                continue
            if detail is None:
                print(f"第{rid}回 は試合情報が見つかりません（未販売/存在しない）。")
                continue
            path, data = save_round(detail, today)
            summarize(data)
            print(f"  → 保存: {path}")
        return

    discover_and_save(today)


if __name__ == "__main__":
    main()
