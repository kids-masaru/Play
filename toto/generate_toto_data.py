"""ダッシュボード用の toto 表示データを生成する。(T10 最小版 / F4・F5 の入力)

入力:
  toto/data/round_<回号>.json          (fetch_toto_round.py)
  toto/data/gemini_round_<回号>.json    (predict_gemini.py) ※あれば
出力:
  dashboard/public/daily_data/toto_info.json

表示は toto（13試合）を主軸（無ければ mini-A組）。各試合に
  - 統計モデルの P(H/D/A)（Geminiデータ内 stats を流用。国際試合等は null）
  - Gemini の 予想(H/D/A)・自信度・推論
を結合する。複数回が販売中なら「締切が最も近い回」を既定で出す（予想が急ぎな回）。

CLI:
  python toto/generate_toto_data.py            # 締切が最も近い販売中の回
  python toto/generate_toto_data.py 1635       # 回号を指定
"""
import os
import sys
import io
import json
import glob
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "..", "dashboard", "public", "daily_data")
OUT_JSON = os.path.join(OUT_DIR, "toto_info.json")

DISPLAY_KUJI_ORDER = ["toto", "mini_a", "mini_b"]  # 表示に使うくじ（先にあるものを採用）


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def gemini_index(gem_data):
    """Gemini予測を (date,home,away) で引ける dict に。"""
    idx = {}
    if not gem_data:
        return idx
    for p in gem_data.get("predictions", []):
        idx[(p.get("date"), p.get("home"), p.get("away"))] = p
    return idx


def pick_display_kuji(round_data):
    """表示に使うくじ種別キーを返す。"""
    for k in DISPLAY_KUJI_ORDER:
        sec = round_data["kuji"].get(k)
        if sec and sec.get("matches"):
            return k, sec
    # どれも無ければ最初に見つかったもの
    for k, sec in round_data["kuji"].items():
        if sec.get("matches"):
            return k, sec
    return None, None


def build(round_no):
    rpath = os.path.join(DATA_DIR, f"round_{round_no}.json")
    if not os.path.exists(rpath):
        print(f"[ERROR] {rpath} がありません。先に fetch_toto_round.py を実行してください。")
        return None
    round_data = load_json(rpath)

    gpath = os.path.join(DATA_DIR, f"gemini_round_{round_no}.json")
    gem = load_json(gpath) if os.path.exists(gpath) else None
    gidx = gemini_index(gem)

    kuji_key, sec = pick_display_kuji(round_data)
    if not sec:
        print(f"[ERROR] 第{round_no}回に表示できる試合がありません。")
        return None

    # 答え合わせ結果（あれば）を match_id で引けるように
    spath = os.path.join(DATA_DIR, f"settled_{round_no}.json")
    settled = load_json(spath) if os.path.exists(spath) else None
    sidx = {r["match_id"]: r for r in settled["results"]} if settled else {}

    matches = []
    for m in sec["matches"]:
        key = (m.get("date"), m.get("home"), m.get("away"))
        g = gidx.get(key)
        mid = f"{round_no}-{m.get('no')}"
        sres = sidx.get(mid, {})
        matches.append({
            "match_id": mid,
            "no": m.get("no"),
            "date": m.get("date"),
            "kickoff": m.get("kickoff"),
            "home": m.get("home"),
            "away": m.get("away"),
            "stats": (g or {}).get("stats"),
            "gemini_pick": (g or {}).get("pick", ""),
            "gemini_confidence": (g or {}).get("confidence", ""),
            "gemini_reasoning": (g or {}).get("reasoning", ""),
            "result": sres.get("actual", ""),  # 確定結果 H/D/A（未確定は空）
        })

    return {
        "round": round_no,
        "kuji": kuji_key,
        "deadline": sec.get("deadline", ""),
        "result_date": sec.get("result_date", ""),
        "generated_date": datetime.date.today().isoformat(),
        "has_gemini": gem is not None,
        "settled": bool(settled and settled.get("n_settled")),
        "summary": settled.get("summary") if settled else None,
        "matches": matches,
    }


def choose_round(args):
    """表示する回号を決める。
    引数指定があればそれ。無ければ「販売中（締切が今日以降）で締切が最も近い回」、
    販売中が無ければ「最新（回号最大）の回」を返す（＝終了直後は結果表示に回る）。"""
    nums = [int(a) for a in args if a.isdigit()]
    if nums:
        return nums[0]
    today = datetime.date.today().isoformat()
    on_sale = []   # (deadline, round_no)
    latest = None  # round_no
    for p in glob.glob(os.path.join(DATA_DIR, "round_*.json")):
        try:
            d = load_json(p)
        except Exception:
            continue
        _, sec = pick_display_kuji(d)
        dl = (sec or {}).get("deadline", "") if sec else ""
        rno = d["round"]
        latest = rno if latest is None else max(latest, rno)
        # 締切日（'YYYY-MM-DD HH:MM' の日付部分）が今日以降なら販売中扱い
        if dl and dl[:10] >= today:
            on_sale.append((dl, rno))
    if on_sale:
        on_sale.sort()
        return on_sale[0][1]
    return latest


def main():
    args = sys.argv[1:]
    round_no = choose_round(args)
    if round_no is None:
        print("対象の round_*.json がありません。fetch_toto_round.py を先に実行してください。")
        return

    data = build(round_no)
    if data is None:
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    n_gem = sum(1 for m in data["matches"] if m["gemini_pick"])
    n_stat = sum(1 for m in data["matches"] if m["stats"])
    print(f"=== toto表示データ生成 ===")
    print(f"第{data['round']}回 ({data['kuji']}) 試合{len(data['matches'])} "
          f"/ 締切 {data['deadline']}")
    print(f"Gemini予想あり {n_gem} / 統計予想あり {n_stat}")
    print(f"→ {os.path.abspath(OUT_JSON)}")


if __name__ == "__main__":
    main()
