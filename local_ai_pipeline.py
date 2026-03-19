import os
import time
import random
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone

# --- 設定 ---
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "deepseek-r1:14b"
DATA_DIR = "daily_data"

PROG_FILE = os.path.join(DATA_DIR, "daily_raw_race_data.csv")
RES_FILE  = os.path.join(DATA_DIR, "daily_history_results.csv")
PRED_FILE = os.path.join(DATA_DIR, "daily_predictions.csv")
REFL_FILE = os.path.join(DATA_DIR, "daily_reflections.csv")
STATS_FILE = os.path.join(DATA_DIR, "daily_player_course_stats.csv")
KNOWLEDGE_FILE = "expert_knowledge.json"

def load_knowledge():
    if os.path.exists(KNOWLEDGE_FILE):
        with open(KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

import json

def call_deepseek(prompt, max_retries=3):
    """ローカルOllama DeepSeekを呼び出す"""
    for attempt in range(max_retries):
        try:
            response = requests.post(OLLAMA_URL, json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 4000
                }
            }, timeout=300)
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                print(f"  [WARN] Ollama応答エラー (HTTP {response.status_code}): {response.text[:200]}")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(10)
            else:
                return f"[ERROR] {str(e)}"
    return "[ERROR] 失敗"

def load_data(filepath):
    if os.path.exists(filepath):
        return pd.read_csv(filepath)
    return pd.DataFrame()

def save_data(df, filepath):
    df.to_csv(filepath, index=False, encoding='utf-8')

# =========================================================
# Phase 1: 予測フェーズ (マルチエージェント)
# =========================================================
def run_predictions():
    print("\n=== Phase 1: 明日のレース予測（マルチエージェント討論） ===", flush=True)
    df_prog = load_data(PROG_FILE)
    if df_prog.empty:
        print("  > 出走表データがありません。")
        return
        
    df_pred = load_data(PRED_FILE)
    if df_pred.empty:
        # PRED_FILEが存在しない場合、空のDFにカラムを定義
        df_pred = pd.DataFrame(columns=["RaceID", "Date", "Venue", "R", "Prediction", "Log"])

    # 明日の日付（JST）
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    target_date = (now_jst + timedelta(days=1)).strftime('%Y-%m-%d') if now_jst.hour >= 18 else now_jst.strftime('%Y-%m-%d')

    # 対象日のレースを抽出
    # 出走表は1レース6行あるので、IDでグループ化してレースデータを組み立てる
    target_races = df_prog[df_prog['Date'].astype(str) == target_date]
    if target_races.empty:
        print(f"  > {target_date} の出走表データがありません。")
        return

    # 既に予測済みのRaceIDを取得
    predicted_ids = set(df_pred['RaceID'].astype(str).unique()) if not df_pred.empty else set()

    grouped = target_races.groupby('ID')
    
    # ─── LightGBM（モック）による全レースの期待値算出と上位10レース抽出 ───
    print(f"  > LightGBMモック: 全 {len(grouped)} レースの期待値を瞬時に計算・選抜中...", flush=True)
    race_scores = []
    skipped_count = 0
    
    for race_id, group in grouped:
        if str(race_id) in predicted_ids:
            skipped_count += 1
            continue
        # モック期待値（1.0〜1.5のランダム値。本番ではLightGBMの期待値スコアが入ります）
        expected_value = random.uniform(1.0, 1.5) 
        race_scores.append((race_id, expected_value, group))
        
    if skipped_count > 0:
        print(f"  > 予測済み {skipped_count} 件をスキップ")
        
    knowledge = load_knowledge()
    knowledge_str = json.dumps(knowledge, ensure_ascii=False, indent=2)

    # 期待値の高い順にソートして上位10レースを厳選
    race_scores.sort(key=lambda x: x[1], reverse=True)
    top_races = race_scores[:10]
    
    if not top_races:
        print(f"  > 新規に予測すべきレースがありませんでした。")
        return
        
    print(f"  > 激アツ抽出完了: 上位 {len(top_races)} レースに対し『統合天才AI (Expert Knowledge版)』のディープ推論を開始します。\n")

    new_preds = []
    processed = 0
    total = len(top_races)
    
    # コース別成績の読み込み
    df_stats = load_data(STATS_FILE)
    stats_dict = {}
    if not df_stats.empty:
        stats_dict = df_stats.set_index('PlayerID').to_dict('index')
    
    for race_id, expected_value, group in top_races:
        venue = group['Venue'].iloc[0]
        r = group['R'].iloc[0]
        date_val = group['Date'].iloc[0]
        
        print(f"  [{processed+1}/{total}] {venue} {r}R ({race_id}) の推論を開始します... (期待値: {expected_value:.2f})", flush=True)
        start_time = time.time()
        
        racer_info = []
        for _, row in group.iterrows():
            lane = int(row['Lane'])
            pid = str(row['PlayerID'])
            base_info = f"{lane}号艇: {row['Name']} (モーター:{row['Motor']}, ランク:{row['Rank']}, 全国勝率:{row['WinRate']})"
            
            # コース別成績の追加
            if pid in stats_dict:
                s = stats_dict[pid]
                c_win = s.get(f'C{lane}_Win', 0)
                c_2in = s.get(f'C{lane}_2in', 0)
                c_3in = s.get(f'C{lane}_3in', 0)
                course_info = f" [当コース実績: 1着率{c_win}%, 2連率{c_2in}%, 3連率{c_3in}%]"
                base_info += course_info
            
            racer_info.append(base_info)
        prompt_data = "\n".join(racer_info)

        # 1. 統合天才AIによる推論（1回で済ませる）
        print("    -> 統合天才AI 深い自問自答中...", end=" ", flush=True)
        
        lgb_probs_str = f"【LightGBM仮算出期待値】: 総合スコア {expected_value:.2f}。本命信頼度が高く、かつヒモ荒れの妙味(期待値)が高いです。"
        
        prompt_genius = f"""あなたは日本最高峰の超・天才舟券師AIです。
以下のLightGBMによる機力・データスコアと出走表をもとに、数学的データの視点、本命・展開の視点、穴・波乱の視点の3方向からあなたの脳内で深い自問自答を行い、最も儲かる期待値の高い結論を一つだけ導き出してください。

{lgb_probs_str}

【出走表】
{prompt_data}

【専門家の勝負鉄則・ナレッジベース】
分析の際、以下の専門知識や統計的勝機（エッジ）を考慮に入れ、期待値を最大化してください：
{knowledge_str}

出力形式は必ず以下を守ってください：
■展開予想と推奨理由
...
■最終推奨買い目
（1-2-3, 1-3-2 のように買い目のみを記載）"""
        
        judge_response = call_deepseek(prompt_genius)
        print("完了")
        
        elapsed = time.time() - start_time
        log_text = f"【天才AI 統合推論ログ】\n{judge_response}"
        
        new_preds.append({
            "RaceID": race_id,
            "Date": date_val,
            "Venue": venue,
            "R": r,
            "Prediction": judge_response,
            "Log": log_text
        })
        
        processed += 1
        print(f"  -> 分析時間: {elapsed:.0f}秒\n", flush=True)

        # こまめに保存
        df_pred = pd.concat([df_pred, pd.DataFrame([new_preds[-1]])], ignore_index=True)
        save_data(df_pred, PRED_FILE)

    print(f"  予測完了: 新規 {processed} 件")

# =========================================================
# Phase 2: 反省会フェーズ (マルチエージェント)
# =========================================================
def run_reflection():
    print("\n=== Phase 2: 昨日の予測の反省会（自動自己改善） ===", flush=True)
    df_pred = load_data(PRED_FILE)
    df_res = load_data(RES_FILE)
    
    if df_pred.empty or df_res.empty:
        print("  > 予測データまたは結果データがありません。")
        return
        
    df_refl = load_data(REFL_FILE)
    if df_refl.empty:
        df_refl = pd.DataFrame(columns=["RaceID", "Date", "Lesson"])

    reflected_ids = set(df_refl['RaceID'].astype(str).unique()) if not df_refl.empty else set()
    
    # 予測があり、かつ結果データが存在し、まだ反省していないレースを探す
    # 重複回避処理を追加
    df_res_unique = df_res.drop_duplicates(subset=['ID'], keep='last')
    res_dict = df_res_unique.set_index('ID')[['Result', 'Payout']].to_dict('index')
    
    new_refls = []
    processed = 0

    for _, row in df_pred.iterrows():
        if processed >= 10:
            print("  > 過去の未反省データが多数存在するため、本日は最新10件で反省処理を打ち切ります。", flush=True)
            break
            
        race_id = str(row['RaceID'])
        if race_id in reflected_ids:
            continue
            
        if race_id in res_dict:
            # 反省会実施
            prediction = str(row['Prediction'])
            actual_res = res_dict[race_id]['Result']
            actual_pay = res_dict[race_id]['Payout']
            
            print(f"  [{race_id}] の反省会を開始...", flush=True)

            print("    -> 統合反省会AI 分析中...", end=" ", flush=True)
            prompt_lesson = f"""あなたはボートレースの最高峰システム改善分析官です。
以下のAIの「予測」と実際の「結果（答え）」を比較し、なぜその結果になったのか（モーター機力の見誤りか、展開・風の影響か等）を脳内で瞬時に自問自答し、システム改善の「教訓」を1行で抽出してください。

【AIの予測】
{prediction[:300]}

【実際の結果】
{actual_res} ({actual_pay}円)

出力形式は必ず以下を守ってください：
「教訓: 〜」のみを出力"""
            lesson_response = call_deepseek(prompt_lesson)
            print("完了")

            new_refls.append({
                "RaceID": race_id,
                "Date": row['Date'],
                "Lesson": lesson_response
            })
            
            processed += 1
            print(f"  -> 反省完了\n", flush=True)
            
            # こまめに保存
            df_refl = pd.concat([df_refl, pd.DataFrame([new_refls[-1]])], ignore_index=True)
            save_data(df_refl, REFL_FILE)

    print(f"  反省会完了: 新規 {processed} 件")

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    run_predictions()
    run_reflection()
    print("=== 全処理完了 ===")

if __name__ == "__main__":
    main()
