"""過去レースを新モデル(Gemini / 学習Gemma×2)にブラインド予測させて予測CSVに追記する。

なぜ作るか:
  Gemini・学習版Gemma は最近追加したため予測数が数十しかなく、Det(346) や 元Gemma(549)
  と的中率を比べても標本が小さすぎて参考にならない。そこで過去レースにも遡って予測させ、
  予測数を数百規模まで揃えて公正に比較できるようにする。

公正さ(リーク無し)の担保:
  入力は過去の「出走表・オッズ・天候(=レース前に分かる情報のみ)」だけ。着順・結果は一切渡さない。
  当日バッチと完全に同じ predict ロジックを使うので、後出しにならないブラインド予測になる。
  ※学習版Gemmaは微調整モデルのため、学習期間と重なるレースは"暗記"の可能性が残る点に注意
    (1bモデルなので可能性は低いが、参考値として見る前提)。

入力 (dashboard/public/daily_data/):
  daily_predictions.csv      : 予測対象レースの母集合(Det/LLMが予測したレース)
  daily_raw_race_data.csv    : 出走表 (1行=1艇)
  daily_raw_beforeinfo.csv   : 直前情報/天候 (1行=1レース)
  daily_odds_3t.csv          : 3連単オッズ (1行=1組合せ)
出力 (同上, RaceID で upsert=追記):
  daily_gemini_predictions.csv / daily_gemma_predictions.csv / daily_gemma_claude_predictions.csv

使い方 (Gemini を使う場合は credentials.env を読む run_backfill.bat 経由を推奨):
  python backfill_battle_predictions.py --models gemmaft,gemmaclaude --from 2026-03-28
    --models : 対象モデル(カンマ区切り) gemini / gemmaft / gemmaclaude。既定=3つ全部
    --from   : この日付以降を対象 (既定 2026-03-28 = オッズ取得開始日)
    --limit  : 1モデルあたり今回処理する最大レース数 (0=無制限)。Gemini無料枠の分割実行用
    --force  : 既に予測済みの RaceID も上書きで予測し直す

途中でAPIクォータ超過/中断しても SAVE_EVERY 件ごとに保存し、未予測の RaceID だけを
次回処理する(再実行で続きから)。実行後は generate_battle_data.py を回してサマリを再生成すること。
"""
import os
import sys
import io
import re
import time
import argparse
import pandas as pd

# 学習版Gemmaの format_race / call_gemma / parse_response / check_ollama を再利用
# (predict_gemma_ft は import しても本体は走らない=安全。import 時に stdout を
#  UTF-8 化してくれるので、ここで二重ラップしないこと=closed file エラー防止)
import predict_gemma_ft as gm

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")

PREDICTIONS_CSV = os.path.join(DATA_DIR, "daily_predictions.csv")
RACE_DATA_CSV = os.path.join(DATA_DIR, "daily_raw_race_data.csv")
BEFOREINFO_CSV = os.path.join(DATA_DIR, "daily_raw_beforeinfo.csv")
ODDS_CSV = os.path.join(DATA_DIR, "daily_odds_3t.csv")

ODDS_TOP_N = 20
SAVE_EVERY = 20  # この件数ごとに途中保存(クォータ超過/中断に備える)


# ----- Gemini 用プロンプト/パース (generate_gemini_predictions.py と同一) -----
GEMINI_PROMPT = """あなたはボートレース予想のプロです。
以下のレース情報を分析し、まず「買う価値（妙味）があるレースか」を判断してください。
オッズに対して期待値が見込めない（本命が堅すぎてオッズに妙味がない／荒れすぎて読めない等）と
判断した場合は、無理に賭けず「見送り」にしてください。"買わない判断"もプロの腕のうちです。

【会場】{venue} {r}R
【天候】{weather} / 風: {wind_dir} {wind_speed} / 波: {wave} / 水温: {water_temp}

【出走表】
{boats_text}
【3連単オッズ(低い順 上位)】
{odds_text}
以下のフォーマットで必ず回答してください。

[思考]
（推論プロセス、3-5行で。インコース有利か、各艇の調子、オッズに妙味があるか）

[最終見解]
（1-2行で結論。買うなら軸と理由、見送るならその理由）

[買い目]
（妙味があれば3連単を3-5点、1行1点で「1-2-3」形式のみ。
　買う価値がないと判断したら「見送り」とだけ書き、買い目は出さないこと）
"""


def gemini_format(race):
    boats_text = ""
    for b in race["boats"]:
        wr = b.get("win_rate")
        wr_str = f"{wr:.2f}" if wr is not None else "-"
        boats_text += (
            f"{b['lane']}号艇: {b['name']} ({b.get('rank', '-')}) "
            f"勝率{wr_str} モーター#{b.get('motor_no', '-')}\n"
        )
    odds_text = ""
    for o in race["odds_top"][:10]:
        odds_text += f"  {o['combo']}: {o['odds']:.1f}倍\n"
    return GEMINI_PROMPT.format(
        venue=race["venue"], r=race["r"],
        weather=race.get("weather") or "-",
        wind_dir=race.get("wind_dir") or "-",
        wind_speed=race.get("wind_speed") or "-",
        wave=race.get("wave") or "-",
        water_temp=race.get("water_temp") or "-",
        boats_text=boats_text,
        odds_text=odds_text,
    )


def gemini_parse(text):
    sections = {"thought": "", "verdict": "", "picks": []}
    current, skip = None, False
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("[思考]"):
            current = "thought"; continue
        if s.startswith("[最終見解]"):
            current = "verdict"; continue
        if s.startswith("[買い目]"):
            current = "picks"; continue
        if not s:
            if current in ("thought", "verdict"):
                sections[current] += "\n"
            continue
        if current == "thought":
            sections["thought"] += s + "\n"
        elif current == "verdict":
            sections["verdict"] += s + "\n"
        elif current == "picks":
            if "見送り" in s:
                skip = True; continue
            for m in re.findall(r"[1-6]-[1-6]-[1-6]", s):
                a, b, c = m.split("-")
                if len({a, b, c}) == 3:
                    sections["picks"].append(m)
    if skip:
        sections["picks"] = []
    seen, uniq = set(), []
    for p in sections["picks"]:
        if p not in seen:
            seen.add(p); uniq.append(p)
        if len(uniq) >= 5:
            break
    sections["picks"] = uniq
    return sections


# ----- データ読み込み & race_info(races[]) 相当の再構築 -----
def safe_float(v, default=None):
    try:
        f = float(v)
        return default if pd.isna(f) else f
    except (ValueError, TypeError):
        return default


def safe_str(v, default=""):
    if v is None or pd.isna(v):
        return default
    return str(v).strip()


def build_races(from_date):
    """過去の出走表/オッズ/天候から、predict が食える race dict のリストを作る。
    対象 = daily_predictions に存在し、from_date 以降で、出走表とオッズが揃うレース。"""
    preds = pd.read_csv(PREDICTIONS_CSV)
    race_data = pd.read_csv(RACE_DATA_CSV)
    before = pd.read_csv(BEFOREINFO_CSV)
    odds = pd.read_csv(ODDS_CSV)

    preds["Date"] = preds["Date"].astype(str)
    race_data["Date"] = race_data["Date"].astype(str)
    odds["Date"] = odds["Date"].astype(str)

    preds = preds[preds["Date"] >= from_date].copy()
    race_data = race_data[race_data["Date"] >= from_date].copy()
    odds = odds[(odds["Date"] >= from_date) & (odds["Odds"] > 0)].copy()

    # オッズ: RaceID(ID) -> 上位N [{combo, odds(float)}]
    odds_by_race = {}
    for rid, grp in odds.groupby("ID"):
        top = grp.nsmallest(ODDS_TOP_N, "Odds")[["Combination", "Odds"]]
        odds_by_race[str(rid)] = [
            {"combo": str(r["Combination"]), "odds": round(safe_float(r["Odds"], 0.0), 1)}
            for _, r in top.iterrows()
        ]

    # 出走表: ID -> [boat]
    boats_by_race = {}
    for rid, grp in race_data.groupby("ID"):
        boats = []
        for _, r in grp.sort_values("Lane").iterrows():
            boats.append({
                "lane": int(r["Lane"]),
                "name": safe_str(r["Name"]),
                "motor_no": safe_str(r["Motor"]),
                "rank": safe_str(r["Rank"]),
                "win_rate": safe_float(r["WinRate"]),
            })
        boats_by_race[str(rid)] = boats

    # 直前情報/天候: ID -> rec
    before_by_race = {}
    for _, r in before.iterrows():
        rid = str(r["ID"])
        rec = {
            "weather": safe_str(r.get("Weather")),
            "wind_speed": safe_str(r.get("WindSpeed")),
            "wind_dir": safe_str(r.get("WindDir")),
            "wave": safe_str(r.get("Wave")),
            "water_temp": safe_str(r.get("WaterTemp")),
        }
        for i in range(1, 7):
            rec[f"b{i}_weight"] = safe_str(r.get(f"B{i}_Weight"))
            rec[f"b{i}_ex_time"] = safe_float(r.get(f"B{i}_ExTime"))
        before_by_race[rid] = rec

    # predictions の各レースを race dict 化(出走表+オッズが揃うものだけ)
    races = []
    seen = set()
    for _, p in preds.sort_values(["Date", "R"]).iterrows():
        rid = str(p["RaceID"])
        if rid in seen:
            continue
        seen.add(rid)
        boats = boats_by_race.get(rid)
        odds_top = odds_by_race.get(rid)
        if not boats or not odds_top:
            continue  # 入力が揃わないレースは対象外
        binfo = before_by_race.get(rid, {})
        for b in boats:
            lane = b["lane"]
            b["weight"] = binfo.get(f"b{lane}_weight")
            b["ex_time"] = binfo.get(f"b{lane}_ex_time")
        races.append({
            "race_id": rid,
            "date": safe_str(p["Date"]),
            "venue": safe_str(p["Venue"]),
            "r": int(p["R"]),
            "weather": binfo.get("weather", ""),
            "wind_speed": binfo.get("wind_speed", ""),
            "wind_dir": binfo.get("wind_dir", ""),
            "wave": binfo.get("wave", ""),
            "water_temp": binfo.get("water_temp", ""),
            "boats": boats,
            "odds_top": odds_top,
        })
    return races


# ----- upsert 保存 -----
def upsert_csv(path, rows):
    new_df = pd.DataFrame(rows)
    if os.path.exists(path):
        try:
            old = pd.read_csv(path)
            if "RaceID" in old.columns and len(new_df):
                old = old[~old["RaceID"].astype(str).isin(new_df["RaceID"].astype(str))]
            combined = pd.concat([old, new_df], ignore_index=True)
        except Exception as e:
            print(f"  [WARN] 既存CSV読込失敗、新規分のみ保存: {type(e).__name__}: {e}")
            combined = new_df
    else:
        combined = new_df
    combined.to_csv(path, index=False, encoding="utf-8")
    return len(combined)


class QuotaStop(Exception):
    """Gemini のクォータ超過。これ以上叩かず保存して終了する合図。"""


# ----- モデル別 predict -----
def predict_gemma_row(race, model, tag):
    text = gm.call_gemma(gm.format_race(race), model)
    parsed = gm.parse_response(text)
    stakes = ", ".join(f"{p}:100" for p in parsed["picks"][:5])
    return {
        "RaceID": race["race_id"], "Date": race["date"],
        "Venue": race["venue"], "R": race["r"],
        f"Prediction_{tag}": parsed["reasoning"][:1500],
        f"Log_{tag}": text.strip()[:2500],
        f"Stakes_{tag}": stakes,
    }


def make_gemini_predict():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY 未設定。run_backfill.bat 経由(credentials.env)で実行してください。")
        sys.exit(1)
    import google.generativeai as genai
    from google.api_core import exceptions as gexc
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))

    def predict(race):
        try:
            resp = model.generate_content(gemini_format(race))
            parsed = gemini_parse(resp.text)
        except gexc.ResourceExhausted as e:
            raise QuotaStop(str(e))
        except Exception as e:
            print(f"    [ERR] {type(e).__name__}: {e}")
            parsed = {"thought": "", "verdict": "", "picks": []}
        stakes = ", ".join(f"{p}:100" for p in parsed["picks"][:5])
        time.sleep(1.5)  # rate limit 余裕
        return {
            "RaceID": race["race_id"], "Date": race["date"],
            "Venue": race["venue"], "R": race["r"],
            "Prediction_Gemini": parsed["verdict"].strip()[:1500],
            "Log_Gemini": parsed["thought"].strip()[:2500],
            "Stakes_Gemini": stakes,
        }
    return predict


def run_model(name, predict, out_name, races, limit, force):
    out_path = os.path.join(DATA_DIR, out_name)
    done = set()
    if os.path.exists(out_path) and not force:
        try:
            done = set(pd.read_csv(out_path)["RaceID"].astype(str))
        except Exception:
            pass
    todo = [r for r in races if r["race_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"\n===== [{name}] 対象 {len(todo)} レース (既存 {len(done)} スキップ / 母集合 {len(races)}) =====")

    results = []
    stopped = False
    try:
        for i, race in enumerate(todo, 1):
            row = predict(race)
            results.append(row)
            if i % 10 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {race['date']} {race['venue']}{race['r']}R", flush=True)
            if i % SAVE_EVERY == 0:
                upsert_csv(out_path, results)
    except QuotaStop as e:
        stopped = True
        print(f"  [STOP] Gemini クォータ超過のため中断: {str(e)[:120]}")
    except KeyboardInterrupt:
        stopped = True
        print("  [STOP] 中断(Ctrl+C)")

    if results:
        total = upsert_csv(out_path, results)
        print(f"[{name}] 保存: 今回 {len(results)} / 累計 {total}{' (途中)' if stopped else ''}")
    else:
        print(f"[{name}] 今回保存分なし")
    return not stopped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="gemini,gemmaft,gemmaclaude",
                    help="対象モデル(カンマ区切り): gemini / gemmaft / gemmaclaude")
    ap.add_argument("--from", dest="from_date", default="2026-03-28",
                    help="この日付以降を対象 (既定=オッズ取得開始日)")
    ap.add_argument("--limit", type=int, default=0, help="1モデルあたり最大処理レース数 (0=無制限)")
    ap.add_argument("--force", action="store_true", help="予測済みRaceIDも再予測")
    args = ap.parse_args()

    wanted = [m.strip() for m in args.models.split(",") if m.strip()]
    limit = args.limit or None

    print(f"対象モデル: {wanted} / from={args.from_date} / limit={limit or '無制限'} / force={args.force}")
    print("race_info(過去) を再構築中...")
    races = build_races(args.from_date)
    print(f"予測可能レース(出走表+オッズ揃い): {len(races)}")

    # Ollama 系を使うなら起動/登録チェック
    if "gemmaft" in wanted and not gm.check_ollama("gemma-boat:1b"):
        wanted.remove("gemmaft")
    if "gemmaclaude" in wanted and not gm.check_ollama("gemma-boat-claude:1b"):
        wanted.remove("gemmaclaude")

    if "gemini" in wanted:
        run_model("Gemini", make_gemini_predict(),
                  "daily_gemini_predictions.csv", races, limit, args.force)
    if "gemmaft" in wanted:
        run_model("GemmaFT(Gemini先生)",
                  lambda r: predict_gemma_row(r, "gemma-boat:1b", "GemmaFT"),
                  "daily_gemma_predictions.csv", races, limit, args.force)
    if "gemmaclaude" in wanted:
        run_model("GemmaClaude(Claude先生)",
                  lambda r: predict_gemma_row(r, "gemma-boat-claude:1b", "GemmaClaude"),
                  "daily_gemma_claude_predictions.csv", races, limit, args.force)

    print("\n全モデル完了。次に `python generate_battle_data.py` でサマリを再生成してください。")


if __name__ == "__main__":
    main()
