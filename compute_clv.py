"""CLV（Closing Line Value）集計スクリプト。

各予測者（Claude/Grok/Gemini/Det弟子…）の買い目について、
「朝オッズ（予測時点）」→「締切オッズ」の市場の動きを測り、
当たり外れとは独立の"妙味を先取りできたか"を CLV(pp) で評価する。

背景（Hugging Face の ash1402/ai-sports-prediction-index を参考に導入）:
  ROI は運が混ざるが、CLV は「締切前に良いオッズを取れていたか」を測る先行指標。
  プロのスポーツベッティングでは ROI より信頼される。

CLV の定義:
  1レース内で、朝・締切それぞれ implied prob p=1/odds を計算し、
  両スナップショットに共通する買い目集合で正規化（Σp=1）。
  ある買い目 c の CLV_pp = (締切の正規化prob − 朝の正規化prob) × 100。
  プラス = 締切までに市場がその買い目へ寄った = 朝の時点で妙味を先取りできていた。

データ:
  朝オッズ   : daily_data/daily_odds_3t.csv         （前売り。予測時点に近い）
  締切オッズ : daily_data/closing_odds_3t.csv        （closing_odds_runner.py が夜に取得）
  予測買い目 : daily_data/daily_<model>_predictions.csv（直近8日ローリング）
  永続ログ   : daily_data/clv_prediction_log.csv      （買い目を8日超えて保持＝本スクリプトが追記）

出力:
  dashboard/public/daily_data/clv_summary.json  （モデル別の平均CLV等）

使い方:
  python compute_clv.py             # 通常運用（ログ追記→締切ありレースで集計→JSON）
  python compute_clv.py --selftest  # 5月のbackfill締切で計算エンジンの妥当性を検証
"""
import os
import re
import sys
import csv
import json
import glob
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
DAILY = os.path.join(HERE, "daily_data")
MORNING_ODDS = os.path.join(DAILY, "daily_odds_3t.csv")
CLOSING_ODDS = os.path.join(DAILY, "closing_odds_3t.csv")
PRED_LOG = os.path.join(DAILY, "clv_prediction_log.csv")
OUT_JSON = os.path.join(HERE, "dashboard", "public", "daily_data", "clv_summary.json")

# 予測者ごとの表示名（ファイル名 daily_<key>_predictions.csv の <key> → ラベル）
MODEL_LABELS = {
    "claude": "Claude",
    "codex": "Codex",
    "gemini": "Gemini",
    "grok": "Grok",
    "gemma": "Gemma弟子",
    "gemma_claude": "Qwen弟子(Claude先生)",
    "gemma_grok_x": "Qwen弟子(Grok+X先生)",
}

# 集計に必要な最低レース数。これ未満は status="accruing"（参考値／蓄積中）とする。
MIN_RACES_ACTIVE = 30

COMBO_RE = re.compile(r"[1-6]-[1-6]-[1-6]")


def _now_jst_str():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")


def parse_combos(text):
    """予測テキストから重複なしの買い目リストを取り出す（1着2着3着が相異なるもののみ）。"""
    out = []
    for m in COMBO_RE.findall(str(text)):
        a, b, c = m.split("-")
        if len({a, b, c}) == 3 and m not in out:
            out.append(m)
    return out


# =========================================================
# 1) 予測ログの永続化（8日ローリングを超えて買い目を保持）
# =========================================================
def append_predictions_to_log():
    """daily_<model>_predictions.csv の当日分を clv_prediction_log.csv に追記（RaceID+model で重複排除）。"""
    files = sorted(glob.glob(os.path.join(DAILY, "daily_*_predictions.csv")))
    # daily_predictions.csv（Det/LLM合体・別構造）は対象外。model名が取れるものだけ。
    rows = []
    for path in files:
        base = os.path.basename(path)
        m = re.match(r"daily_(.+)_predictions\.csv$", base)
        if not m:
            continue
        model = m.group(1)
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
        except Exception as e:
            print(f"  [WARN] 読込失敗 {base}: {e}")
            continue
        # 買い目カラム（Prediction_ で始まる最初の列）を探す
        pred_col = next((c for c in df.columns if c.lower().startswith("prediction")), None)
        rid_col = "RaceID" if "RaceID" in df.columns else ("ID" if "ID" in df.columns else None)
        if pred_col is None or rid_col is None:
            continue
        for _, r in df.iterrows():
            combos = parse_combos(r[pred_col])
            if not combos:
                continue
            rows.append({
                "RaceID": str(r[rid_col]).strip(),
                "Date": str(r.get("Date", "")).strip(),
                "model": model,
                "combos": ",".join(combos),
            })

    if not rows:
        print("  [INFO] 追記対象の予測がありません。")
        return

    new_df = pd.DataFrame(rows)
    if os.path.exists(PRED_LOG):
        old = pd.read_csv(PRED_LOG, dtype=str).fillna("")
        merged = pd.concat([old, new_df], ignore_index=True)
    else:
        merged = new_df
    # RaceID+model で最新を残す（当日の買い目更新に追従）
    merged = merged.drop_duplicates(subset=["RaceID", "model"], keep="last")
    merged.to_csv(PRED_LOG, index=False, quoting=csv.QUOTE_MINIMAL)
    print(f"  予測ログ更新: {PRED_LOG}（累計 {len(merged)} 件, 今回入力 {len(new_df)} 件）")


# =========================================================
# 2) オッズ読み込み（必要なレースIDだけ・チャンク読み）
# =========================================================
def load_odds_for_races(path, race_ids):
    """指定 race_ids の {race_id: {combo: odds(float)}} を返す。大きいCSVはチャンクで読む。"""
    want = set(race_ids)
    out = {}
    if not os.path.exists(path):
        return out
    for ch in pd.read_csv(path, dtype=str, chunksize=300000):
        ch = ch[ch["ID"].isin(want)]
        if ch.empty:
            continue
        for rid, grp in ch.groupby("ID"):
            d = out.setdefault(str(rid), {})
            for _, row in grp.iterrows():
                try:
                    o = float(row["Odds"])
                except (ValueError, TypeError):
                    continue
                if o > 0:
                    d[str(row["Combination"])] = o
    return out


# =========================================================
# 3) CLV 計算
# =========================================================
def normalized_implied(odds_map, combos):
    """combos（共通集合）に限定して implied prob=1/odds を正規化した dict を返す。"""
    raw = {c: 1.0 / odds_map[c] for c in combos}
    s = sum(raw.values())
    if s <= 0:
        return None
    return {c: v / s for c, v in raw.items()}


def clv_for_race(picks, morning, closing):
    """1レース分。picks=買い目リスト。morning/closing={combo:odds}。
    戻り値: (買い目ごとのCLV_ppリスト) 計算不能なら []。"""
    common = set(morning) & set(closing)
    if len(common) < 3:
        return []
    pm = normalized_implied(morning, common)
    pc = normalized_implied(closing, common)
    if pm is None or pc is None:
        return []
    res = []
    for c in picks:
        if c in common:
            res.append((pc[c] - pm[c]) * 100.0)
    return res


def aggregate(pred_log_df, morning_all, closing_all):
    """モデル別に CLV を集計して dict を返す。"""
    summary = {}
    for model, mdf in pred_log_df.groupby("model"):
        per_pick = []          # 全買い目のCLV_pp
        race_avgs = []         # レース平均CLV_pp
        graded_races = 0
        for _, r in mdf.iterrows():
            rid = str(r["RaceID"])
            morning = morning_all.get(rid)
            closing = closing_all.get(rid)
            if not morning or not closing:
                continue  # 締切オッズ未取得のレースはまだ採点不能
            picks = [c for c in str(r["combos"]).split(",") if c]
            vals = clv_for_race(picks, morning, closing)
            if not vals:
                continue
            graded_races += 1
            per_pick.extend(vals)
            race_avgs.append(sum(vals) / len(vals))

        if graded_races == 0:
            summary[model] = {
                "label": MODEL_LABELS.get(model, model),
                "status": "accruing",
                "graded_races": 0,
                "note": "締切オッズ待ち（closing_odds_runner.py 稼働後に蓄積）",
            }
            continue

        avg_clv = sum(race_avgs) / len(race_avgs)
        pos_rate = 100.0 * sum(1 for v in per_pick if v > 0) / len(per_pick)
        summary[model] = {
            "label": MODEL_LABELS.get(model, model),
            "status": "active" if graded_races >= MIN_RACES_ACTIVE else "accruing",
            "graded_races": graded_races,
            "picks": len(per_pick),
            "avg_clv_pp": round(avg_clv, 3),
            "positive_rate_pct": round(pos_rate, 1),
        }
    return summary


# =========================================================
# 通常運用
# =========================================================
def run_normal():
    print("=== CLV 集計 開始 ===")
    print("[1] 予測ログ永続化")
    append_predictions_to_log()

    if not os.path.exists(PRED_LOG):
        print("[INFO] 予測ログが空のため終了。")
        return

    log = pd.read_csv(PRED_LOG, dtype=str).fillna("")
    race_ids = sorted(log["RaceID"].unique())
    print(f"[2] オッズ突合（対象 {len(race_ids)} レース）")
    morning_all = load_odds_for_races(MORNING_ODDS, race_ids)
    closing_all = load_odds_for_races(CLOSING_ODDS, race_ids)
    print(f"    朝オッズあり {len(morning_all)} / 締切オッズあり {len(closing_all)} レース")

    print("[3] モデル別 CLV 集計")
    summary = aggregate(log, morning_all, closing_all)

    payload = {
        "generated_at": _now_jst_str(),
        "metric": "CLV_pp (closing implied prob - morning implied prob, normalized)",
        "min_races_active": MIN_RACES_ACTIVE,
        "sources": {
            "morning_odds": os.path.basename(MORNING_ODDS),
            "closing_odds": os.path.basename(CLOSING_ODDS),
        },
        "models": summary,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[4] 出力: {OUT_JSON}")

    # コンソール要約
    print("\n--- モデル別 CLV ---")
    for model, s in summary.items():
        if s.get("status") == "accruing" and s.get("graded_races", 0) == 0:
            print(f"  {s['label']:<22} : 蓄積中（締切オッズ待ち）")
        else:
            print(f"  {s['label']:<22} : 平均CLV {s['avg_clv_pp']:+.2f}pp / "
                  f"プラス率 {s['positive_rate_pct']}% / {s['graded_races']}レース [{s['status']}]")
    print("\n=== 完了 ===")


# =========================================================
# 自己検証: 5月の backfill 締切で計算エンジンの妥当性を確認
# =========================================================
def run_selftest():
    """締切backfillがある期間で、固定戦略のCLVを計算しエンジンの妥当性を確認する。
    （モデル別ではない。エンジンが妥当な数値を返すかの証明用）"""
    print("=== CLV 自己検証（5月backfill締切 × 固定戦略）===")
    bf_dir = os.path.join(HERE, "past_data", "past_odds_3t_backfill")
    files = sorted(glob.glob(os.path.join(bf_dir, "202605*.csv")))[-3:]  # 5月終盤3日
    if not files:
        print("[SKIP] backfill 締切ファイルが見つかりません。")
        return

    # 固定戦略: 「朝オッズで人気上位3点を買う」＝素朴なフォロー戦略（CLVは0近辺になるはず）
    #          「朝オッズで4〜6番人気を買う」＝逆張り（本命化すればプラス、離れればマイナス）
    strategies = {"人気上位3点(順張り)": (0, 3), "4-6番人気(逆張り)": (3, 6)}

    for path in files:
        date8 = os.path.basename(path)[:8]
        bf = pd.read_csv(path, dtype=str)
        race_ids = sorted(bf["ID"].unique())
        closing_all = load_odds_for_races(path, race_ids)
        morning_all = load_odds_for_races(MORNING_ODDS, race_ids)
        common_races = [r for r in race_ids if r in morning_all and r in closing_all]
        if not common_races:
            print(f"  {date8}: 朝×締切が揃うレースなし")
            continue

        print(f"\n  [{date8}] 検証レース {len(common_races)} 件")
        for label, (lo, hi) in strategies.items():
            per_pick = []
            for rid in common_races:
                morning = morning_all[rid]
                # 朝オッズ人気順に並べ、lo:hi 番人気を買い目に
                ranked = sorted(morning, key=lambda c: morning[c])
                picks = ranked[lo:hi]
                per_pick.extend(clv_for_race(picks, morning, closing_all[rid]))
            if per_pick:
                avg = sum(per_pick) / len(per_pick)
                pos = 100.0 * sum(1 for v in per_pick if v > 0) / len(per_pick)
                print(f"    {label:<18}: 平均CLV {avg:+.2f}pp / プラス率 {pos:.0f}% "
                      f"({len(per_pick)}点)")
    print("\n（順張りは0近辺、逆張りは大きく振れる＝エンジンが市場の動きを捉えられていればOK）")
    print("=== 自己検証 完了 ===")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        run_selftest()
    else:
        run_normal()
