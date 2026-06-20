"""予測対戦ダッシュボード用の当日データJSON生成。

入力 (dashboard/public/daily_data/ から):
  daily_predictions.csv     : AI予測上位レース
  daily_raw_race_data.csv   : 出走表 (1行=1艇)
  daily_raw_beforeinfo.csv  : 直前情報 (1行=1レース)
  daily_odds_3t.csv         : 3連単オッズ (1行=1組合せ)

出力:
  dashboard/public/daily_data/daily_race_info.json

朝バッチ後 or 手動で実行する想定。
"""
import os
import json
import time
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")

PREDICTIONS_CSV = os.path.join(DATA_DIR, "daily_predictions.csv")
RACE_DATA_CSV = os.path.join(DATA_DIR, "daily_raw_race_data.csv")
BEFOREINFO_CSV = os.path.join(DATA_DIR, "daily_raw_beforeinfo.csv")
ODDS_CSV = os.path.join(DATA_DIR, "daily_odds_3t.csv")
GEMINI_CSV = os.path.join(DATA_DIR, "daily_gemini_predictions.csv")  # 任意
GEMMA_FT_CSV = os.path.join(DATA_DIR, "daily_gemma_predictions.csv")  # 任意(学習版Gemma/Gemini先生)
GEMMA_CLAUDE_CSV = os.path.join(DATA_DIR, "daily_gemma_claude_predictions.csv")  # 任意(学習版Gemma/Claude先生)

OUTPUT_JSON = os.path.join(DATA_DIR, "daily_race_info.json")
OUTPUT_AI_SUMMARY = os.path.join(DATA_DIR, "ai_predictions_summary.json")

ODDS_TOP_N = 20  # 各レースのオッズ表示上位件数


def safe_float(v, default=None):
    try:
        f = float(v)
        if pd.isna(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def safe_str(v, default=""):
    if v is None or pd.isna(v):
        return default
    return str(v).strip()


def main():
    t0 = time.time()
    print("[1/5] 入力CSVを読み込み...")
    preds = pd.read_csv(PREDICTIONS_CSV)
    race_data = pd.read_csv(RACE_DATA_CSV)
    before = pd.read_csv(BEFOREINFO_CSV)
    odds = pd.read_csv(ODDS_CSV)

    print(f"  predictions: {len(preds):,} レース")
    print(f"  race_data:   {len(race_data):,} 艇 ({len(race_data)//6} レース)")
    print(f"  beforeinfo:  {len(before):,} レース")
    print(f"  odds:        {len(odds):,} 行")

    # 当日 = predictions の最新日付
    target_date = preds["Date"].max()
    print(f"  対象日: {target_date}")

    # 当日に絞り込み
    preds = preds[preds["Date"] == target_date].copy()
    race_data = race_data[race_data["Date"] == target_date].copy()
    before = before[before["Date"] == target_date].copy()
    odds = odds[odds["Date"] == target_date].copy()
    print(f"  当日フィルタ後: predictions={len(preds)}, race_data={len(race_data)}, before={len(before)}, odds={len(odds)}")

    print("[2/5] オッズを race_id で辞書化...")
    odds = odds[odds["Odds"] > 0].copy()
    odds_by_race = {}
    for rid, grp in odds.groupby("ID"):
        top = grp.nsmallest(ODDS_TOP_N, "Odds")[["Combination", "Odds"]]
        odds_by_race[str(rid)] = [
            {"combo": str(r["Combination"]), "odds": round(safe_float(r["Odds"], 0.0), 1)}
            for _, r in top.iterrows()
        ]

    print("[3/5] 出走表を race_id × Lane で辞書化...")
    boats_by_race = {}
    for rid, grp in race_data.groupby("ID"):
        boats = []
        for _, r in grp.sort_values("Lane").iterrows():
            boats.append({
                "lane": int(r["Lane"]),
                "name": safe_str(r["Name"]),
                "player_id": safe_str(r["PlayerID"]),
                "motor_no": safe_str(r["Motor"]),
                "rank": safe_str(r["Rank"]),
                "win_rate": safe_float(r["WinRate"]),
                "count": safe_float(r["Count"]),
            })
        boats_by_race[str(rid)] = boats

    print("[4/5] 直前情報を race_id で辞書化...")
    before_by_race = {}
    for _, r in before.iterrows():
        rid = str(r["ID"])
        rec = {
            "weather": safe_str(r["Weather"]),
            "wind_speed": safe_str(r["WindSpeed"]),
            "wind_dir": safe_str(r["WindDir"]),
            "wave": safe_str(r["Wave"]),
            "water_temp": safe_str(r["WaterTemp"]),
        }
        # 各艇の直前情報
        for i in range(1, 7):
            rec[f"b{i}_weight"] = safe_str(r.get(f"B{i}_Weight"))
            rec[f"b{i}_tilt"] = safe_float(r.get(f"B{i}_Tilt"))
            rec[f"b{i}_ex_time"] = safe_float(r.get(f"B{i}_ExTime"))
        before_by_race[rid] = rec

    # Gemini予測 (任意、ファイルがあれば)
    gemini_by_race = {}
    if os.path.exists(GEMINI_CSV):
        gem = pd.read_csv(GEMINI_CSV)
        gem = gem[gem["Date"] == target_date].copy() if "Date" in gem.columns else gem
        for _, g in gem.iterrows():
            rid = safe_str(g.get("RaceID"))
            if not rid:
                continue
            gemini_by_race[rid] = {
                "stakes": safe_str(g.get("Stakes_Gemini")),
                "prediction": safe_str(g.get("Prediction_Gemini"))[:1500],
                "log": safe_str(g.get("Log_Gemini"))[:2500],
            }
        print(f"  Gemini予測: {len(gemini_by_race)} レース")

    # 学習版Gemma予測 (任意、ファイルがあれば)
    gemmaft_by_race = {}
    if os.path.exists(GEMMA_FT_CSV):
        gmf = pd.read_csv(GEMMA_FT_CSV)
        gmf = gmf[gmf["Date"] == target_date].copy() if "Date" in gmf.columns else gmf
        for _, g in gmf.iterrows():
            rid = safe_str(g.get("RaceID"))
            if not rid:
                continue
            gemmaft_by_race[rid] = {
                "stakes": safe_str(g.get("Stakes_GemmaFT")),
                "prediction": safe_str(g.get("Prediction_GemmaFT"))[:1500],
                "log": safe_str(g.get("Log_GemmaFT"))[:2500],
            }
        print(f"  学習版Gemma(Gemini先生)予測: {len(gemmaft_by_race)} レース")

    # 学習版Gemma(Claude先生)予測 (任意、ファイルがあれば)
    gemmaclaude_by_race = {}
    if os.path.exists(GEMMA_CLAUDE_CSV):
        gmc = pd.read_csv(GEMMA_CLAUDE_CSV)
        gmc = gmc[gmc["Date"] == target_date].copy() if "Date" in gmc.columns else gmc
        for _, g in gmc.iterrows():
            rid = safe_str(g.get("RaceID"))
            if not rid:
                continue
            gemmaclaude_by_race[rid] = {
                "stakes": safe_str(g.get("Stakes_GemmaClaude")),
                "prediction": safe_str(g.get("Prediction_GemmaClaude"))[:1500],
                "log": safe_str(g.get("Log_GemmaClaude"))[:2500],
            }
        print(f"  学習版Gemma(Claude先生)予測: {len(gemmaclaude_by_race)} レース")

    print("[5/5] 統合してJSON出力...")
    races_out = []
    for _, p in preds.iterrows():
        rid = str(p["RaceID"])
        boats = boats_by_race.get(rid, [])
        before_info = before_by_race.get(rid, {})
        # 各艇に直前情報をマージ
        for b in boats:
            lane = b["lane"]
            b["weight"] = before_info.get(f"b{lane}_weight")
            b["tilt"] = before_info.get(f"b{lane}_tilt")
            b["ex_time"] = before_info.get(f"b{lane}_ex_time")

        races_out.append({
            "race_id": rid,
            "date": safe_str(p["Date"]),
            "venue": safe_str(p["Venue"]),
            "r": int(p["R"]),
            "weather": before_info.get("weather", ""),
            "wind_speed": before_info.get("wind_speed", ""),
            "wind_dir": before_info.get("wind_dir", ""),
            "wave": before_info.get("wave", ""),
            "water_temp": before_info.get("water_temp", ""),
            "boats": boats,
            "odds_top": odds_by_race.get(rid, []),
            "ai_picks_det": safe_str(p.get("Stakes_Det")),
            "ai_picks_llm": safe_str(p.get("Stakes")),
            "ai_log": safe_str(p.get("Log"))[:2500],  # LLM推論ログ (表示用)
            "ai_prediction": safe_str(p.get("Prediction"))[:1500],  # LLM最終見解
            "ai_picks_gemini": gemini_by_race.get(rid, {}).get("stakes", ""),
            "ai_prediction_gemini": gemini_by_race.get(rid, {}).get("prediction", ""),
            "ai_log_gemini": gemini_by_race.get(rid, {}).get("log", ""),
            "ai_picks_gemmaft": gemmaft_by_race.get(rid, {}).get("stakes", ""),
            "ai_prediction_gemmaft": gemmaft_by_race.get(rid, {}).get("prediction", ""),
            "ai_log_gemmaft": gemmaft_by_race.get(rid, {}).get("log", ""),
            "ai_picks_gemmaclaude": gemmaclaude_by_race.get(rid, {}).get("stakes", ""),
            "ai_prediction_gemmaclaude": gemmaclaude_by_race.get(rid, {}).get("prediction", ""),
            "ai_log_gemmaclaude": gemmaclaude_by_race.get(rid, {}).get("log", ""),
        })

    out = {
        "date": str(target_date),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "races": races_out,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    size_kb = os.path.getsize(OUTPUT_JSON) / 1024
    print(f"出力: {OUTPUT_JSON} ({size_kb:.1f} KB), レース数: {len(races_out)}")

    # 全期間のAI予測サマリJSON (RaceID -> {stakes, stakes_det, stakes_gemini}) for 履歴比較
    print("[+] AI予測サマリ (全期間) を生成...")
    preds_all = pd.read_csv(PREDICTIONS_CSV)
    ai_summary = {}
    for _, p in preds_all.iterrows():
        rid = safe_str(p.get("RaceID"))
        if not rid:
            continue
        ai_summary[rid] = {
            "stakes": safe_str(p.get("Stakes")),
            "stakes_det": safe_str(p.get("Stakes_Det")),
        }
    # Gemini予測 (もしあれば全期間分も統合)
    if os.path.exists(GEMINI_CSV):
        gem_all = pd.read_csv(GEMINI_CSV)
        for _, g in gem_all.iterrows():
            rid = safe_str(g.get("RaceID"))
            if not rid:
                continue
            if rid not in ai_summary:
                ai_summary[rid] = {"stakes": "", "stakes_det": ""}
            ai_summary[rid]["stakes_gemini"] = safe_str(g.get("Stakes_Gemini"))
    # 学習版Gemma(Gemini先生)予測 (もしあれば全期間分も統合)
    if os.path.exists(GEMMA_FT_CSV):
        gmf_all = pd.read_csv(GEMMA_FT_CSV)
        for _, g in gmf_all.iterrows():
            rid = safe_str(g.get("RaceID"))
            if not rid:
                continue
            if rid not in ai_summary:
                ai_summary[rid] = {"stakes": "", "stakes_det": ""}
            ai_summary[rid]["stakes_gemmaft"] = safe_str(g.get("Stakes_GemmaFT"))
    # 学習版Gemma(Claude先生)予測 (もしあれば全期間分も統合)
    if os.path.exists(GEMMA_CLAUDE_CSV):
        gmc_all = pd.read_csv(GEMMA_CLAUDE_CSV)
        for _, g in gmc_all.iterrows():
            rid = safe_str(g.get("RaceID"))
            if not rid:
                continue
            if rid not in ai_summary:
                ai_summary[rid] = {"stakes": "", "stakes_det": ""}
            ai_summary[rid]["stakes_gemmaclaude"] = safe_str(g.get("Stakes_GemmaClaude"))
    with open(OUTPUT_AI_SUMMARY, "w", encoding="utf-8") as f:
        json.dump(ai_summary, f, ensure_ascii=False)
    size_kb2 = os.path.getsize(OUTPUT_AI_SUMMARY) / 1024
    print(f"出力: {OUTPUT_AI_SUMMARY} ({size_kb2:.1f} KB), {len(ai_summary)} レース")

    print(f"\n完了 ({time.time()-t0:.1f}s)")


if __name__ == "__main__":
    main()
