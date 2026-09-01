"""ダッシュボード用の toto 表示データを生成する。(T10 最小版 / F4・F5 の入力)

入力:
  toto/data/round_<回号>.json          (fetch_toto_round.py)
  toto/data/gemini_round_<回号>.json    (predict_gemini.py) ※あれば
  toto/data/codex_round_<回号>.json     (predict_codex.py) ※あれば
  toto/data/claude_round_<回号>.json    (predict_claude.py) ※あれば
出力:
  dashboard/public/daily_data/toto_info.json

表示は toto（13試合）を主軸（無ければ mini-A組）。各試合に
  - 統計モデルの P(H/D/A)（AI予測とは独立して都度計算。国際試合等は null）
  - Gemini の 予想(H/D/A)・自信度・推論
  - Codex の 予想(H/D/A)・自信度・推論
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

from predict_gemini import build_context, load_stats_model

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
OUT_DIR = os.path.join(ROOT, "..", "dashboard", "public", "daily_data")
OUT_JSON = os.path.join(OUT_DIR, "toto_info.json")          # 既定表示の1回（後方互換）
OUT_ALL_JSON = os.path.join(OUT_DIR, "toto_rounds.json")    # 全回（過去の答え合わせ閲覧用）

DISPLAY_KUJI_ORDER = ["toto", "mini_a", "mini_b"]  # 表示に使うくじ（先にあるものを採用）
KUJI_LABEL = {"toto": "toto (13試合)", "mini_a": "mini toto-A (5試合)", "mini_b": "mini toto-B (5試合)"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def prediction_index(prediction_data):
    """AI予測を (date,home,away) で引ける dict に。"""
    idx = {}
    if not prediction_data:
        return idx
    for p in prediction_data.get("predictions", []):
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


def load_payouts():
    """公式自動取得を基本にし、手入力がある項目だけを上書きして返す。"""
    official_path = os.path.join(DATA_DIR, "official_results.json")
    manual_path = os.path.join(DATA_DIR, "manual_payouts.json")
    try:
        merged = load_json(official_path) if os.path.exists(official_path) else {}
    except Exception:
        merged = {}
    try:
        manual = load_json(manual_path) if os.path.exists(manual_path) else {}
    except Exception:
        manual = {}
    for round_no, values in manual.items():
        if not isinstance(values, dict):
            continue
        target = merged.setdefault(str(round_no), {})
        for key, value in (values or {}).items():
            if key == "detail":
                target.setdefault("detail", {}).update(value or {})
            else:
                target[key] = value
    return merged


def load_official_actual(round_no, kuji_key):
    """公式結果の並びをH/D/Aで返す。未取得なら空配列。"""
    path = os.path.join(DATA_DIR, "official_results.json")
    if not os.path.exists(path):
        return []
    try:
        round_result = load_json(path).get(str(round_no), {})
        return (round_result.get("results", {}) or {}).get(kuji_key, []) or []
    except Exception:
        return []


def load_game_actual(round_no):
    """settled_<回>.json から (date,home,away)->H/D/A の確定結果マップを作る。
    toto(13試合)は mini(5試合)の試合を包含するので、これ1つで全くじの結果を引ける。"""
    spath = os.path.join(DATA_DIR, f"settled_{round_no}.json")
    if not os.path.exists(spath):
        return {}
    settled = load_json(spath)
    out = {}
    for r in settled.get("results", []):
        if r.get("actual"):
            out[(r.get("date"), r.get("home"), r.get("away"))] = r["actual"]
    return out


def build(round_no, kuji_key=None, stats_model=None):
    """指定くじ(無ければ表示既定=toto優先)の1ビューを組み立てる。
    match_id は試合ベース（toto内の試合番号）に統一＝ユーザー予測がくじ間で引き継がれる。"""
    rpath = os.path.join(DATA_DIR, f"round_{round_no}.json")
    if not os.path.exists(rpath):
        print(f"[ERROR] {rpath} がありません。先に fetch_toto_round.py を実行してください。")
        return None
    round_data = load_json(rpath)

    gpath = os.path.join(DATA_DIR, f"gemini_round_{round_no}.json")
    gem = load_json(gpath) if os.path.exists(gpath) else None
    gidx = prediction_index(gem)
    cpath = os.path.join(DATA_DIR, f"codex_round_{round_no}.json")
    codex = load_json(cpath) if os.path.exists(cpath) else None
    cidx = prediction_index(codex)
    clpath = os.path.join(DATA_DIR, f"claude_round_{round_no}.json")
    claude = load_json(clpath) if os.path.exists(clpath) else None
    clidx = prediction_index(claude)
    game_actual = load_game_actual(round_no)
    payouts = load_payouts()

    if kuji_key is None:
        kuji_key, sec = pick_display_kuji(round_data)
    else:
        sec = round_data["kuji"].get(kuji_key)
    if not sec or not sec.get("matches"):
        return None

    # 試合(date,home,away)->toto内の試合番号。match_id を全くじで一致させる。
    toto_sec = round_data["kuji"].get("toto") or {}
    toto_no_by_game = {(m.get("date"), m.get("home"), m.get("away")): m.get("no")
                       for m in toto_sec.get("matches", [])}

    matches = []
    official_actual = load_official_actual(round_no, kuji_key)
    stat_n = stat_h = gem_n = gem_h = codex_n = codex_h = claude_n = claude_h = 0
    for match_index, m in enumerate(sec["matches"]):
        key = (m.get("date"), m.get("home"), m.get("away"))
        g = gidx.get(key) or {}
        c = cidx.get(key) or {}
        cl = clidx.get(key) or {}
        # toto公式のくじ結果を最優先にし、未取得時だけJリーグ収集結果へ戻す。
        actual = official_actual[match_index] if match_index < len(official_actual) else game_actual.get(key, "")
        gp = g.get("pick", "")
        cp = c.get("pick", "")
        clp = cl.get("pick", "")
        # 統計確率はAI予測の成否と切り離す。古い予測ファイルに無い場合も最新履歴から補う。
        stats = g.get("stats") or c.get("stats") or cl.get("stats")
        if not stats and stats_model:
            _, stats = build_context(m, stats_model)
        sp = (stats or {}).get("pick", "")
        if actual:
            if gp:
                gem_n += 1
                if gp == actual:
                    gem_h += 1
            if cp:
                codex_n += 1
                if cp == actual:
                    codex_h += 1
            if clp:
                claude_n += 1
                if clp == actual:
                    claude_h += 1
            if sp:
                stat_n += 1
                if sp == actual:
                    stat_h += 1
        # 試合ベースの match_id（toto番号。mini も同じ試合は同じID）
        toto_no = toto_no_by_game.get(key, m.get("no"))
        matches.append({
            "match_id": f"{round_no}-{toto_no}",
            "no": m.get("no"),
            "date": m.get("date"),
            "kickoff": m.get("kickoff"),
            "home": m.get("home"),
            "away": m.get("away"),
            "stats": stats,
            "gemini_pick": gp,
            "gemini_confidence": g.get("confidence", ""),
            "gemini_reasoning": g.get("reasoning", ""),
            "codex_pick": cp,
            "codex_confidence": c.get("confidence", ""),
            "codex_reasoning": c.get("reasoning", ""),
            "claude_pick": clp,
            "claude_confidence": cl.get("confidence", ""),
            "claude_reasoning": cl.get("reasoning", ""),
            "result": actual,  # 確定結果 H/D/A（未確定は空）
        })

    n_settled = sum(1 for m in matches if m["result"])
    round_pay = payouts.get(str(round_no), {}) or {}
    payout = round_pay.get(kuji_key, None)  # 1等当せん金(円/100円). None=未取得, 0=該当なし
    # 等級別明細（あれば）: [{rank, amount(円), count(口数)}, ...]
    payout_detail = (round_pay.get("detail", {}) or {}).get(kuji_key, None)
    return {
        "round": round_no,
        "kuji": kuji_key,
        "kuji_label": KUJI_LABEL.get(kuji_key, kuji_key),
        "payout": payout,
        "payout_detail": payout_detail,
        "deadline": sec.get("deadline", ""),
        "result_date": sec.get("result_date", ""),
        "generated_date": datetime.date.today().isoformat(),
        "has_gemini": gem is not None,
        "has_codex": codex is not None,
        "has_claude": claude is not None,
        "settled": bool(n_settled),
        "summary": {"stat": {"n": stat_n, "hits": stat_h},
                    "gemini": {"n": gem_n, "hits": gem_h},
                    "codex": {"n": codex_n, "hits": codex_h},
                    "claude": {"n": claude_n, "hits": claude_h}},
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

    stats_model = load_stats_model()
    data = build(round_no, "toto", stats_model) or build(round_no, stats_model=stats_model)
    if data is None:
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    n_gem = sum(1 for m in data["matches"] if m["gemini_pick"])
    n_codex = sum(1 for m in data["matches"] if m["codex_pick"])
    n_claude = sum(1 for m in data["matches"] if m["claude_pick"])
    n_stat = sum(1 for m in data["matches"] if m["stats"])
    print(f"=== toto表示データ生成 ===")
    print(f"第{data['round']}回 ({data['kuji']}) 試合{len(data['matches'])} "
          f"/ 締切 {data['deadline']}")
    print(
        f"Gemini予想あり {n_gem} / Codex予想あり {n_codex} / "
        f"Claude予想あり {n_claude} / 統計予想あり {n_stat}"
    )
    print(f"→ {os.path.abspath(OUT_JSON)}")

    # --- 全回 × 全くじ種別(toto/mini-A/mini-B) を出力（回切替＋くじ切替で閲覧）---
    order = {k: i for i, k in enumerate(DISPLAY_KUJI_ORDER)}
    all_views = []
    for p in glob.glob(os.path.join(DATA_DIR, "round_*.json")):
        try:
            rno = load_json(p)["round"]
        except Exception:
            continue
        for kuji_key in DISPLAY_KUJI_ORDER:
            d = build(rno, kuji_key, stats_model)
            if d:
                all_views.append(d)
    all_views.sort(key=lambda x: (-x["round"], order.get(x["kuji"], 9)))  # 新しい回→toto/miniA/miniB順
    out_all = {
        "default_round": data["round"],
        "default_key": f"{data['round']}-toto",
        "rounds": all_views,
    }
    with open(OUT_ALL_JSON, "w", encoding="utf-8") as f:
        json.dump(out_all, f, ensure_ascii=False, indent=2)
    settled_cnt = sum(1 for r in all_views if r.get("settled"))
    print(f"→ {os.path.abspath(OUT_ALL_JSON)} (全{len(all_views)}ビュー / 答え合わせ済み {settled_cnt})")


if __name__ == "__main__":
    main()
