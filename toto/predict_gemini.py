"""Gemini API で toto 対象試合の 1X2 を予測する。(F3 / T5)

入力: toto/data/round_<回号>.json  （fetch_toto_round.py の出力）
出力: toto/data/gemini_round_<回号>.json
  { round, model, generated_date, predictions: [ {date,home,away,kickoff,
      pick(H/D/A), confidence(高/中/低), reasoning, stats(任意)} ] }

予測単位は「回号内の全ユニーク試合」(toto/mini-A/mini-B/goal3 の和集合)。
Jリーグの対戦なら統計モデル(predict_stats)の確率と直近フォームを材料として渡す。
国際試合(代表)等で履歴が無い場合は、Gemini の一般知識のみで推論させる。

必要: 環境変数 GEMINI_API_KEY（既存ボートと同じく credentials.env で設定し、
      バッチ実行時に環境へ展開される。本スクリプトは .env を直接読まない）

CLI:
  python toto/predict_gemini.py                 # 販売中の round_*.json を全て予測
  python toto/predict_gemini.py 1635            # 回号を指定
  python toto/predict_gemini.py 1635 --dry-run  # API を呼ばずプロンプトと材料を確認
"""
import os
import sys
import io
import re
import json
import glob
import time
import datetime
import pandas as pd

# Windows cmd の cp932 stdout 対策（reconfigure は冪等で、import先の同種処理と衝突しない）
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
MATCHES_CSV = os.path.join(DATA_DIR, "jleague_matches.csv")

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
SLEEP_BETWEEN_CALLS = 1.5
KUJI_ORDER = ["toto", "mini_a", "mini_b", "goal3"]

# fetch_toto_round の予測対象（mini/goal3 は toto の部分集合とは限らないため和集合を取る）

PROMPT_TEMPLATE = """あなたはサッカーの予想に詳しいアナリストです。
以下の1試合について、結果を「ホーム勝(H) / 引分(D) / アウェイ勝(A)」の3択で予想してください。

【試合】{home}（ホーム） vs {away}（アウェイ）
【キックオフ】{date} {kickoff}
{context}
必ず次のフォーマットで日本語で回答してください（学習教材なので推論を丁寧に）。

[推論]
（なぜその結果になりそうか。チーム力・直近の調子・ホームアドバンテージ・データの見立てなどを3-5行で）

[予想]
（H か D か A のいずれか1文字だけ）

[自信度]
（高 / 中 / 低 のいずれか）
"""

STATS_CONTEXT = """【参考データ（統計モデルによる推定）】
- 勝敗確率の推定: ホーム勝 {ph:.0%} / 引分 {pd:.0%} / アウェイ勝 {pa:.0%}
- {home} 直近フォーム: {home_form}
- {away} 直近フォーム: {away_form}
（この推定は得点期待値ベースの簡易モデル。鵜呑みにせず参考程度に）
"""

NO_STATS_CONTEXT = """【参考データ】
- このカードはJリーグの蓄積データが無い対戦（代表戦・カップ戦・海外等）。
  一般的なチーム力の知識をもとに推論してください。
"""


# ---------- Jリーグ統計の材料づくり ----------

def load_stats_model():
    """predict_stats.StatsModel を Jリーグ履歴で学習して返す。失敗時 None。"""
    try:
        sys.path.insert(0, ROOT)
        from predict_stats import StatsModel
        df = pd.read_csv(MATCHES_CSV, dtype={"date": str})
        df = df[df["result"].isin(["H", "D", "A"])].copy()
        model = StatsModel().fit(df)
        teams = sorted(set(df["home"]) | set(df["away"]))
        return model, teams, df
    except Exception as e:
        print(f"  [WARN] 統計モデル準備に失敗（Gemini単独で続行）: {e}")
        return None, [], None


def normalize_team(toto_name, jleague_teams):
    """toto表記のチーム名を Jリーグ履歴の表記に対応づける。無ければ None。
    完全一致 → 双方向の部分一致（短い略称ゆれを吸収）。"""
    if not toto_name or not jleague_teams:
        return None
    if toto_name in jleague_teams:
        return toto_name
    cands = [t for t in jleague_teams if toto_name in t or t in toto_name]
    if len(cands) == 1:
        return cands[0]
    return None


def recent_form(df, team, n=5):
    """直近n試合の W/D/L 文字列を返す（新しい順）。"""
    rows = df[(df["home"] == team) | (df["away"] == team)].sort_values(
        ["date", "kickoff"]).tail(n)
    out = []
    for _, r in rows.iterrows():
        if r["result"] == "D":
            out.append("分")
        elif (r["home"] == team and r["result"] == "H") or \
             (r["away"] == team and r["result"] == "A"):
            out.append("勝")
        else:
            out.append("負")
    return "".join(reversed(out)) if out else "データ無し"


def build_context(match, stats):
    """1試合分のプロンプト context（統計材料）を返す。stats=(model,teams,df) or None。"""
    if not stats or stats[0] is None:
        return NO_STATS_CONTEXT, None
    model, teams, df = stats
    h = normalize_team(match["home"], teams)
    a = normalize_team(match["away"], teams)
    if not h or not a:
        return NO_STATS_CONTEXT, None
    pr = model.predict(h, a, match.get("date") or "9999-99-99")
    ctx = STATS_CONTEXT.format(
        ph=pr["p_H"], pd=pr["p_D"], pa=pr["p_A"],
        home=match["home"], away=match["away"],
        home_form=recent_form(df, h), away_form=recent_form(df, a),
    )
    stat_out = {"p_H": round(pr["p_H"], 4), "p_D": round(pr["p_D"], 4),
                "p_A": round(pr["p_A"], 4), "pick": pr["pick"]}
    return ctx, stat_out


# ---------- Gemini応答のパース ----------

def parse_response(text):
    """[推論]/[予想]/[自信度] を取り出す。pick は H/D/A に正規化。"""
    sec = {"reasoning": "", "pick": "", "confidence": ""}
    cur = None
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[推論]"):
            cur = "reasoning"; continue
        if s.startswith("[予想]"):
            cur = "pick"; continue
        if s.startswith("[自信度]"):
            cur = "confidence"; continue
        if not s:
            continue
        if cur == "reasoning":
            sec["reasoning"] += s + "\n"
        elif cur == "pick" and not sec["pick"]:
            m = re.search(r"[HDA]", s)
            if m:
                sec["pick"] = m.group(0)
        elif cur == "confidence" and not sec["confidence"]:
            m = re.search(r"[高中低]", s)
            if m:
                sec["confidence"] = m.group(0)
    sec["reasoning"] = sec["reasoning"].strip()
    return sec


# ---------- 予測本体 ----------

def collect_unique_matches(round_data):
    """回号データから全ユニーク試合を (date,home,away) キーで和集合。"""
    seen = {}
    for k in KUJI_ORDER:
        sec = round_data["kuji"].get(k)
        if not sec:
            continue
        for m in sec.get("matches", []):
            key = (m.get("date"), m.get("home"), m.get("away"))
            if key not in seen:
                seen[key] = {"date": m.get("date"), "kickoff": m.get("kickoff"),
                             "home": m.get("home"), "away": m.get("away")}
    # 日付→KO順に整列
    return sorted(seen.values(), key=lambda x: (x["date"] or "", x["kickoff"] or ""))


def predict_round(round_data, stats, model_obj, dry_run=False):
    matches = collect_unique_matches(round_data)
    print(f"  対象 {len(matches)} 試合（toto/mini/goal3 和集合）")
    preds = []
    for i, m in enumerate(matches, 1):
        ctx, stat_out = build_context(m, stats)
        prompt = PROMPT_TEMPLATE.format(
            home=m["home"], away=m["away"],
            date=m["date"], kickoff=m["kickoff"], context=ctx)
        if dry_run:
            print(f"\n--- [{i}/{len(matches)}] {m['home']} vs {m['away']} "
                  f"({m['date']} {m['kickoff']}) stats={'有' if stat_out else '無'}")
            print(prompt)
            preds.append({**m, "pick": "", "confidence": "",
                          "reasoning": "(dry-run)", "stats": stat_out})
            continue
        try:
            t0 = time.time()
            resp = model_obj.generate_content(prompt)
            parsed = parse_response(resp.text)
            print(f"  [{i}/{len(matches)}] {m['home']} vs {m['away']}: "
                  f"{parsed['pick'] or '?'} (自信 {parsed['confidence'] or '?'}) "
                  f"{time.time()-t0:.1f}s")
        except Exception as e:
            print(f"  [{i}/{len(matches)}] {m['home']} vs {m['away']} "
                  f"[ERR] {type(e).__name__}: {e}")
            parsed = {"reasoning": "", "pick": "", "confidence": ""}
        preds.append({**m, "pick": parsed["pick"], "confidence": parsed["confidence"],
                      "reasoning": parsed["reasoning"][:2000], "stats": stat_out})
        time.sleep(SLEEP_BETWEEN_CALLS)
    return preds


def save(round_no, preds, today):
    path = os.path.join(DATA_DIR, f"gemini_round_{round_no}.json")
    data = {"round": round_no, "model": MODEL_NAME,
            "generated_date": today.isoformat(), "predictions": preds}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def target_round_files(args):
    """CLI引数から対象 round_*.json のパス一覧を決める。"""
    nums = [a for a in args if a.isdigit()]
    if nums:
        return [os.path.join(DATA_DIR, f"round_{n}.json") for n in nums]
    return sorted(glob.glob(os.path.join(DATA_DIR, "round_*.json")))


def main():
    today = datetime.date.today()
    args = sys.argv[1:]
    dry_run = "--dry-run" in args

    files = target_round_files(args)
    files = [f for f in files if os.path.exists(f)]
    if not files:
        print("対象の round_*.json がありません。先に fetch_toto_round.py を実行してください。")
        return

    # Gemini クライアント（dry-run 時は不要）
    model_obj = None
    if not dry_run:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("[ERROR] 環境変数 GEMINI_API_KEY が未設定です。")
            print("       credentials.env に GEMINI_API_KEY=AIza... を設定し、")
            print("       バッチ経由（環境変数を展開した状態）で実行してください。")
            print("       プロンプト確認だけなら --dry-run を付けてAPI無しで実行できます。")
            return
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model_obj = genai.GenerativeModel(MODEL_NAME)

    stats = load_stats_model()
    print(f"=== Gemini toto予測 ({MODEL_NAME}{' / DRY-RUN' if dry_run else ''}) ===")

    for f in files:
        with open(f, "r", encoding="utf-8") as fp:
            round_data = json.load(fp)
        rno = round_data["round"]
        print(f"\n第{rno}回 ({os.path.basename(f)})")
        preds = predict_round(round_data, stats, model_obj, dry_run=dry_run)
        if dry_run:
            continue
        path = save(rno, preds, today)
        done = sum(1 for p in preds if p["pick"])
        print(f"  → 保存: {path}  予想確定 {done}/{len(preds)}")


if __name__ == "__main__":
    main()
