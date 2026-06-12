"""試合結果を取り込み、各回の答え合わせ（H/D/A確定・的中判定）を行う。(T11 / F5)

入力:
  toto/data/round_<回号>.json          対象試合
  toto/data/gemini_round_<回号>.json    AI(統計/Gemini)の予想 ※あれば
  toto/data/jleague_matches.csv         Jリーグの結果（collect_jleague.py が更新）
出力:
  toto/data/settled_<回号>.json
    { round, settled_date, results:[ {match_id,home,away,date,
        actual(H/D/A or ""), stats_pick, stats_hit, gemini_pick, gemini_hit} ],
      summary:{ stat:{n,hits}, gemini:{n,hits} } }

結果が取れるのは Jリーグの対戦のみ（国際試合等はデータ源が別途必要なため actual="" のまま）。
冪等: 何度実行しても同じ結果（確定済みは上書き、未確定は空のまま）。

CLI:
  python toto/settle_results.py            # 全 round_*.json を答え合わせ
  python toto/settle_results.py 1635       # 回号を指定
"""
import os
import sys
import io
import json
import glob
import datetime
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
MATCHES_CSV = os.path.join(DATA_DIR, "jleague_matches.csv")

# 表示と同じく toto を主軸に答え合わせ
DISPLAY_KUJI_ORDER = ["toto", "mini_a", "mini_b"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jleague():
    """Jリーグ結果を (date, home, away)->result で引ける形に。teams集合も返す。"""
    if not os.path.exists(MATCHES_CSV):
        return {}, set()
    df = pd.read_csv(MATCHES_CSV, dtype={"date": str})
    df = df[df["result"].isin(["H", "D", "A"])]
    teams = set(df["home"]) | set(df["away"])
    lut = {}
    for _, r in df.iterrows():
        lut[(str(r["date"]), str(r["home"]), str(r["away"]))] = str(r["result"])
    return lut, teams


def pick_display_kuji(round_data):
    for k in DISPLAY_KUJI_ORDER:
        sec = round_data["kuji"].get(k)
        if sec and sec.get("matches"):
            return sec
    for _, sec in round_data["kuji"].items():
        if sec.get("matches"):
            return sec
    return None


def gemini_index(gem):
    idx = {}
    if not gem:
        return idx
    for p in gem.get("predictions", []):
        idx[(p.get("date"), p.get("home"), p.get("away"))] = p
    return idx


def lookup_actual(match, lut, teams, normalize):
    """toto試合のJリーグ実結果(H/D/A)を返す。見つからなければ ''。"""
    h = normalize(match.get("home"), teams)
    a = normalize(match.get("away"), teams)
    if not h or not a:
        return ""
    return lut.get((str(match.get("date")), h, a), "")


def settle_round(round_no, lut, teams, normalize, today):
    rpath = os.path.join(DATA_DIR, f"round_{round_no}.json")
    if not os.path.exists(rpath):
        return None
    round_data = load_json(rpath)
    sec = pick_display_kuji(round_data)
    if not sec:
        return None

    gpath = os.path.join(DATA_DIR, f"gemini_round_{round_no}.json")
    gidx = gemini_index(load_json(gpath) if os.path.exists(gpath) else None)

    results = []
    stat_n = stat_hits = gem_n = gem_hits = 0
    for m in sec["matches"]:
        actual = lookup_actual(m, lut, teams, normalize)
        g = gidx.get((m.get("date"), m.get("home"), m.get("away"))) or {}
        stats_pick = (g.get("stats") or {}).get("pick", "")
        gemini_pick = g.get("pick", "")

        stats_hit = gemini_hit = None
        if actual:
            if stats_pick:
                stat_n += 1
                stats_hit = (stats_pick == actual)
                if stats_hit:
                    stat_hits += 1
            if gemini_pick:
                gem_n += 1
                gemini_hit = (gemini_pick == actual)
                if gemini_hit:
                    gem_hits += 1

        results.append({
            "match_id": f"{round_no}-{m.get('no')}",
            "no": m.get("no"),
            "home": m.get("home"),
            "away": m.get("away"),
            "date": m.get("date"),
            "actual": actual,
            "stats_pick": stats_pick,
            "stats_hit": stats_hit,
            "gemini_pick": gemini_pick,
            "gemini_hit": gemini_hit,
        })

    settled = sum(1 for r in results if r["actual"])
    out = {
        "round": round_no,
        "settled_date": today.isoformat(),
        "n_matches": len(results),
        "n_settled": settled,
        "summary": {
            "stat": {"n": stat_n, "hits": stat_hits},
            "gemini": {"n": gem_n, "hits": gem_hits},
        },
        "results": results,
    }
    return out


def save(out):
    path = os.path.join(DATA_DIR, f"settled_{out['round']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return path


def main():
    today = datetime.date.today()
    args = [a for a in sys.argv[1:] if a.isdigit()]

    # 名前正規化は predict_gemini の実装を再利用（同じ対応規則を使う）
    sys.path.insert(0, ROOT)
    from predict_gemini import normalize_team

    lut, teams = load_jleague()
    if not lut:
        print("[WARN] jleague_matches.csv が無い/空のため、Jリーグ結果の答え合わせはできません。")

    if args:
        rounds = [int(a) for a in args]
    else:
        rounds = []
        for p in glob.glob(os.path.join(DATA_DIR, "round_*.json")):
            try:
                rounds.append(load_json(p)["round"])
            except Exception:
                pass

    print(f"=== 答え合わせ (基準日 {today.isoformat()}) ===")
    for rno in sorted(rounds):
        out = settle_round(rno, lut, teams, normalize_team, today)
        if out is None:
            continue
        path = save(out)
        s = out["summary"]
        sr = f"{s['stat']['hits']}/{s['stat']['n']}" if s['stat']['n'] else "-"
        gr = f"{s['gemini']['hits']}/{s['gemini']['n']}" if s['gemini']['n'] else "-"
        print(f"  第{rno}回: 確定 {out['n_settled']}/{out['n_matches']}試合　"
              f"統計的中 {sr}　Gemini的中 {gr}　→ {os.path.basename(path)}")


if __name__ == "__main__":
    main()
