"""
ボートレースAI予測 - ローカルDeepSeek版
Ollama (deepseek-r1:14b) を使用してレース予測を行い、Google Sheetsに書き込む。

スケジュール: 毎日 03:00 JST（Windowsタスクスケジューラ）
前提: Ollamaが起動中であること
"""

import os
import json
import re
import time
import requests
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- 設定 ---
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "deepseek-r1:14b"
SPREADSHEET_ID = "1ixdf0Ep4DWSYPPED0xwCqwuG0U-aRSyl_5JI801Jk4Q"

# 認証情報
json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "boatraceauto-b2bfa32e72bc.json")
if os.path.exists(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        SERVICE_ACCOUNT_JSON = f.read()
else:
    SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_API_KEY")

def get_sheets_service():
    creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

def read_sheet(service, sheet_name, range_str=None):
    """シートのデータを読み込む"""
    full_range = f"{sheet_name}!{range_str}" if range_str else sheet_name
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range=full_range
        ).execute()
        return result.get('values', [])
    except Exception as e:
        print(f"  [ERROR] シート '{sheet_name}' 読み込み失敗: {e}")
        return []

def write_sheet(service, sheet_name, range_str, values):
    """シートにデータを書き込む"""
    full_range = f"{sheet_name}!{range_str}"
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=full_range,
        valueInputOption='USER_ENTERED', body={'values': values}
    ).execute()

def append_sheet(service, sheet_name, values):
    """シートにデータを追記する"""
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID, range=f'{sheet_name}!A1',
        valueInputOption='USER_ENTERED', body={'values': values}
    ).execute()

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
            }, timeout=300)  # 5分タイムアウト
            
            if response.status_code == 200:
                result = response.json()
                return result.get("response", "")
            else:
                print(f"  [WARN] Ollama応答エラー (HTTP {response.status_code}): {response.text[:200]}")
        except requests.exceptions.ConnectionError:
            print(f"  [ERROR] Ollamaに接続できません。Ollamaが起動しているか確認してください。")
            if attempt < max_retries - 1:
                print(f"  [RETRY] 30秒後にリトライ ({attempt+1}/{max_retries})...")
                time.sleep(30)
            else:
                return "[ERROR] Ollamaに接続できませんでした"
        except requests.exceptions.Timeout:
            print(f"  [WARN] タイムアウト。リトライ ({attempt+1}/{max_retries})...")
            if attempt < max_retries - 1:
                time.sleep(10)
            else:
                return "[ERROR] タイムアウト"
        except Exception as e:
            print(f"  [ERROR] 予期しないエラー: {e}")
            return f"[ERROR] {str(e)}"
    return "[ERROR] 最大リトライ回数超過"

# ==============================================================
# Phase 0: features_daily を raw_race_data から自動生成
# ==============================================================
def build_features_daily(service):
    """raw_race_data → features_daily に変換（AI_Prompt列を含む）"""
    print("\n=== Phase 0: features_daily 生成 ===", flush=True)
    
    raw_data = read_sheet(service, "raw_race_data")
    if len(raw_data) < 2:
        print("  raw_race_data にデータがありません。スキップ。")
        return 0
    
    # 今日以降のデータのみ
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).strftime("%Y-%m-%d")
    
    # 既存の features_daily を確認
    existing_fd = read_sheet(service, "features_daily")
    existing_ids = set()
    if len(existing_fd) > 1:
        for row in existing_fd[1:]:
            if len(row) > 3:
                existing_ids.add(f"{row[3]}_{row[4]}")  # ID_Lane
    
    # beforeinfo データ取得（展示タイム・風向き用）
    beforeinfo = {}
    bi_data = read_sheet(service, "raw_beforeinfo")
    if len(bi_data) > 1:
        for row in bi_data[1:]:
            if len(row) >= 2:
                bi_id = str(row[0])
                beforeinfo[bi_id] = row
    
    # raw_race_data: Date(0), Venue(1), R(2), ID(3), Lane(4), PlayerID(5), Name(6), Motor(7), Rank(8), WinRate(9), Count(10)
    new_rows = []
    for row in raw_data[1:]:
        if len(row) < 10: continue
        
        date_val = row[0]
        # 過去のデータはスキップ
        if date_val < today: continue
        
        unique_key = f"{row[3]}_{row[4]}"
        if unique_key in existing_ids: continue
        
        # AI_Prompt列の生成
        venue = row[1]
        race_no = row[2]
        lane = row[4]
        name = row[6]
        motor = row[7]
        rank = row[8]
        win_rate = row[9]
        
        ai_prompt = f"{lane}号艇: {name} (モーター:{motor}, ランク:{rank}, 勝率:{win_rate})"
        
        # features_daily行: Date, Venue, R, ID, Lane, PlayerID, Name, Motor, Rank, ST(空), Count, AI_Prompt, Tenji(空), Wind(空), Win%(空), 2Ren%(空), 3Ren%(空)
        fd_row = [
            row[0],   # Date
            row[1],   # Venue
            row[2],   # R
            row[3],   # ID
            row[4],   # Lane
            row[5],   # PlayerID
            row[6],   # Name
            row[7],   # Motor
            row[8],   # Rank
            "",       # ST (空)
            row[10] if len(row) > 10 else "",  # Count
            ai_prompt,  # AI_Prompt
            "",       # Tenji
            "",       # Wind
            "",       # Win%
            "",       # 2Ren%
            "",       # 3Ren%
        ]
        new_rows.append(fd_row)
    
    if new_rows:
        append_sheet(service, "features_daily", new_rows)
        print(f"  {len(new_rows)} 行を features_daily に追加しました。")
    else:
        print("  追加すべき新規データはありません。")
    
    return len(new_rows)

# ==============================================================
# Phase 1: プロンプト生成 (generateDailyPrompts)
# ==============================================================
def generate_daily_prompts(service):
    """features_dailyからプロンプトを作成し、AI_Analysisに書き込む"""
    print("\n=== Phase 1: プロンプト生成 ===", flush=True)
    
    # features_daily 読み込み
    data = read_sheet(service, "features_daily")
    if len(data) < 2:
        print("  features_daily にデータがありません。スキップ。")
        return 0
    
    header = data[0]
    rows = data[1:]
    
    # 今日以降のデータのみ
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).strftime("%Y-%m-%d")
    
    # 学習内容を取得
    lessons = get_recent_lessons(service)
    learning_context = ""
    if lessons:
        learning_context = "\n\n【重要：過去の反省点（これを踏まえて予想すること）】\n" + "\n".join(lessons) + "\n"
    
    # レースごとにグループ化
    races = {}
    for row in rows:
        if len(row) < 12: continue
        race_date = row[0]
        if race_date < today: continue
        
        race_id = row[3]
        venue = row[1]
        race_no = row[2]
        prompt_part = row[11] if len(row) > 11 else ""
        
        if not race_id: continue
        if race_id not in races:
            races[race_id] = {"venue": venue, "race_no": race_no, "details": []}
        races[race_id]["details"].append(prompt_part)
    
    # 既存のAI_Analysisを確認
    existing = read_sheet(service, "AI_Analysis")
    processed_ids = set()
    if existing:
        for row in existing[1:]:
            if row:
                processed_ids.add(str(row[0]))
    
    # 新規プロンプト作成
    new_rows = []
    for race_id, info in races.items():
        if str(race_id) in processed_ids: continue
        
        full_prompt = (
            "以下のボートレースデータから、レース展開と推奨買い目を予想してください。"
            + learning_context
            + f"\n\n開催地: {info['venue']} 第{info['race_no']}レース\n"
            + "出走表:\n" + "\n".join(info["details"])
        )
        new_rows.append([race_id, info["venue"], info["race_no"], full_prompt, "", ""])
    
    if new_rows:
        append_sheet(service, "AI_Analysis", new_rows)
        print(f"  {len(new_rows)} 件の新規プロンプトを作成しました。")
    else:
        print("  新規プロンプトはありません。")
    
    return len(new_rows)

# ==============================================================
# Phase 2: ハイブリッド＆マルチエージェントAI予測実行 (Phase 4 & 6)
# ==============================================================
def predict_race_outcomes(service):
    """LightGBMの確率計算と、複数ペルソナによるDeepSeek討論会（アンサンブル）を実行"""
    print("\n=== Phase 2: ハイブリッド予想＆AI討論会実行 ===", flush=True)
    
    data = read_sheet(service, "AI_Analysis")
    if len(data) < 2:
        print("  AI_Analysis にデータがありません。スキップ。")
        return 0
    
    processed = 0
    total_to_process = 0
    
    # 未予測の行をカウント
    for i, row in enumerate(data[1:], start=2):
        if len(row) < 4: continue
        prompt = row[3] if len(row) > 3 else ""
        existing = row[4] if len(row) > 4 else ""
        if prompt and (not existing or str(existing).startswith("[ERROR")):
            total_to_process += 1
    
    if total_to_process == 0:
        print("  予測すべきレースがありません。")
        return 0
    
    print(f"  予測対象: {total_to_process} 件", flush=True)
    
    for i, row in enumerate(data[1:], start=2):
        if len(row) < 4: continue
        prompt = row[3] if len(row) > 3 else ""
        existing = row[4] if len(row) > 4 else ""
        
        if not prompt: continue
        if existing and not str(existing).startswith("[ERROR"): continue
        
        race_id = row[0] if row else "?"
        venue = row[1] if len(row) > 1 else "?"
        race_no = row[2] if len(row) > 2 else "?"
        
        print(f"  [{processed+1}/{total_to_process}] {venue} {race_no}R ({race_id}) の討論を開始します...", flush=True)
        
        start_time = time.time()
        
        # 1. LightGBMによる確率計算（現在は学習用データの準備完了待ちのためモック値または仮推定）
        # ※本番化の際は、ここで生データから特徴量を作成し、model.predict() を実行します。
        lgb_probs_str = "【LightGBM仮算出確率】1号艇: 65%, 2号艇: 15%, 3号艇: 10%, 4号艇: 5%, 5号艇: 3%, 6号艇: 2%"

        # 2. マルチエージェントによる討論（Phase 6）
        print("    -> 数学者AI 推論中...", end=" ", flush=True)
        prompt_math = f"あなたはデータ重視の数学者AIです。以下のLightGBMの確率予測とレースデータを元に、最も期待値の高い論理的な予想と理由を簡潔に出力してください。\n{lgb_probs_str}\n\n【レースデータ】\n{prompt}"
        math_response = call_deepseek(prompt_math)
        print("完了")

        print("    -> 大穴狙いAI 推論中...", end=" ", flush=True)
        prompt_hole = f"あなたは展開や天候の波乱を重視する大穴狙いAIです。以下のデータから、波乱が起きるシナリオ（1号艇が負ける展開）と穴予想を簡潔に出力してください。\n【レースデータ】\n{prompt}"
        hole_response = call_deepseek(prompt_hole)
        print("完了")

        print("    -> 本命党AI 推論中...", end=" ", flush=True)
        prompt_solid = f"あなたは本命重視の堅実なAIです。以下のデータから、最も堅実に決着するシナリオと本命予想を簡潔に出力してください。\n【レースデータ】\n{prompt}"
        solid_response = call_deepseek(prompt_solid)
        print("完了")

        print("    -> 裁判官AI 最終判決中...", end=" ", flush=True)
        prompt_judge = f"""あなたは3人の専門家AIの意見を統合し、最終結論を下す裁判官AIです。
以下の3つの異なる視点の予想を総合的に評価し、最終的な【推奨買い目】と【その見解】を出力してください。

【1. 数学者AIの意見】
{math_response}

【2. 大穴狙いAIの意見】
{hole_response}

【3. 本命党AIの意見】
{solid_response}

出力フォーマット：
■ 裁判官の最終見解：
（理由）
■ 最終推奨買い目：
（買い目）"""
        judge_response = call_deepseek(prompt_judge)
        print("完了")
        
        elapsed = time.time() - start_time
        
        # 結果をシートに書き込み
        # シートのマスには、最終結論と各AIの意見のログをまとめて保存する
        final_output = f"{judge_response}\n\n---\n【討論ログ】\n[数学者] {math_response}\n\n[大穴狙い] {hole_response}\n\n[本命党] {solid_response}"
        write_sheet(service, "AI_Analysis", f"E{i}", [[final_output]])
        
        processed += 1
        print(f"  -> {venue} {race_no}R 完了 (討論時間: {elapsed:.0f}秒)\n", flush=True)
        
        # 少し待機
        time.sleep(2)
    
    print(f"\n  討論・予測完了: {processed}/{total_to_process} 件")
    return processed

# ==============================================================
# Phase 3: マルチエージェント反省会 (Phase 6 拡張)
# ==============================================================
def run_review_cycle(service):
    """昨日の予測を実際の結果と比較して反省会"""
    print("\n=== Phase 3: 反省会 ===", flush=True)
    
    # 結果データ読み込み
    result_data = read_sheet(service, "history_results")
    if len(result_data) < 2:
        print("  history_results にデータがありません。スキップ。")
        return 0
    
    results = {}
    for row in result_data[1:]:
        if len(row) >= 6:
            rid = str(row[3])
            result = row[4]
            payout = row[5]
            if rid and result:
                results[rid] = {"result": result, "payout": payout}
    
    # AI_Analysis 読み込み
    ana_data = read_sheet(service, "AI_Analysis")
    if len(ana_data) < 2:
        print("  AI_Analysis にデータがありません。スキップ。")
        return 0
    
    review_count = 0
    
    for i, row in enumerate(ana_data[1:], start=2):
        if len(row) < 6: continue
        rid = str(row[0])
        ai_response = row[4] if len(row) > 4 else ""
        status = row[5] if len(row) > 5 else ""
        
        # 既にレビュー済み、予想なし、結果なしはスキップ
        if status == "Reviewed": continue
        if not ai_response or str(ai_response).startswith("[ERROR"): continue
        if rid not in results: continue
        
        actual = results[rid]
        
        print(f"  [{rid}] の反省会を開始します...", flush=True)

        print("    -> モーター分析官AI 考察中...", end=" ", flush=True)
        prompt_motor = f"あなたは競艇のモーター分析官AIです。以下の予測と実際の結果を比較し、「機力・モーター・コース適性」の観点から敗因または勝因を1行で考察してください。\n【予測】{ai_response[:1000]}\n【結果】{actual['result']} (配当:{actual['payout']}円)"
        motor_response = call_deepseek(prompt_motor)
        print("完了")

        print("    -> 気象・展開分析官AI 考察中...", end=" ", flush=True)
        prompt_weather = f"あなたは競艇の気象・展開分析官AIです。以下の予測と実際の結果を比較し、「風、波、スタート展開」の観点から敗因または勝因を1行で考察してください。\n【予測】{ai_response[:1000]}\n【結果】{actual['result']} (配当:{actual['payout']}円)"
        weather_response = call_deepseek(prompt_weather)
        print("完了")

        print("    -> 総括マネージャーAI 結論統合中...", end=" ", flush=True)
        reflection_prompt = f"""あなたはボートレース予測システムの総括マネージャーAIです。
過去の予測結果に対する、2人の専門分析官の意見を統合し、次回の予測システム（ルール）改善に向けた【たった1行の教訓】を作成してください。

【実際の結果】決着: {actual['result']}, 配当: {actual['payout']}円
【モーター分析官】{motor_response}
【気象・展開分析官】{weather_response}

出力形式: 「教訓：〜」"""
        
        print(f"  反省中: {rid}...", end=" ", flush=True)
        
        lesson = call_deepseek(reflection_prompt)
        
        if lesson and not lesson.startswith("[ERROR"):
            # AI_Lessonsに追加
            JST = timezone(timedelta(hours=9))
            now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
            append_sheet(service, "AI_Lessons", [[now_str, rid, lesson]])
            
            # ステータス更新
            write_sheet(service, "AI_Analysis", f"F{i}", [["Reviewed"]])
            
            review_count += 1
            print("完了", flush=True)
            time.sleep(1)
        else:
            print("失敗", flush=True)
    
    print(f"\n  反省完了: {review_count} 件")
    return review_count

# ==============================================================
# Phase 4: 選手成績DB更新 (updateRacerStats)
# ==============================================================
def update_racer_stats(service):
    """選手の成績統計を更新（AI不要、計算のみ）"""
    print("\n=== Phase 4: 選手成績DB更新 ===", flush=True)
    
    raw_data = read_sheet(service, "features_daily")
    hist_data = read_sheet(service, "history_results")
    
    if len(raw_data) < 2 or len(hist_data) < 2:
        print("  データ不足。スキップ。")
        return
    
    # 結果マップ作成
    result_map = {}
    for row in hist_data[1:]:
        if len(row) >= 5:
            rid = str(row[3])
            result_str = str(row[4])
            if rid and ("-" in result_str or "/" in result_str):
                result_map[rid] = result_str
    
    # 選手統計計算
    stats = {}
    for row in raw_data[1:]:
        if len(row) < 7: continue
        rid = str(row[3])
        lane = row[4]
        pid = row[5]
        name = row[6]
        
        if not pid or rid not in result_map: continue
        
        if pid not in stats:
            stats[pid] = {"name": name, "runs": 0, "w1": 0, "w2": 0, "w3": 0}
        
        stats[pid]["runs"] += 1
        nums = re.findall(r'\d+', result_map[rid])
        if len(nums) >= 3:
            try:
                lane_int = int(lane)
                if int(nums[0]) == lane_int: stats[pid]["w1"] += 1
                if int(nums[1]) == lane_int: stats[pid]["w2"] += 1
                if int(nums[2]) == lane_int: stats[pid]["w3"] += 1
            except (ValueError, TypeError):
                pass
    
    # 書き込み
    output = []
    for pid, s in stats.items():
        runs = s["runs"]
        if runs == 0: continue
        output.append([
            pid, s["name"], runs, s["w1"], s["w2"], s["w3"],
            f"{s['w1']/runs:.1%}", f"{(s['w1']+s['w2'])/runs:.1%}", 
            f"{(s['w1']+s['w2']+s['w3'])/runs:.1%}"
        ])
    
    if output:
        # 既存データクリア
        try:
            db_data = read_sheet(service, "racer_db")
            if len(db_data) > 1:
                clear_range = f"racer_db!A2:I{len(db_data)}"
                service.spreadsheets().values().clear(
                    spreadsheetId=SPREADSHEET_ID, range=clear_range
                ).execute()
        except:
            pass
        
        # 書き込み
        write_sheet(service, "racer_db", f"A2:I{len(output)+1}", output)
        print(f"  {len(output)} 名の選手データを更新しました。")
    else:
        print("  更新すべきデータがありません。")

# ==============================================================
# Phase 5: アーカイブ (archivePredictions)
# ==============================================================
def archive_predictions(service):
    """Reviewed済みの予測をAI_Archiveに移動"""
    print("\n=== Phase 5: アーカイブ ===", flush=True)
    
    ana_data = read_sheet(service, "AI_Analysis")
    if len(ana_data) < 2:
        print("  アーカイブ対象なし。")
        return 0
    
    JST = timezone(timedelta(hours=9))
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    
    rows_to_archive = []
    rows_to_keep = [ana_data[0]]  # ヘッダー行を保持
    
    for row in ana_data[1:]:
        status = row[5] if len(row) > 5 else ""
        response = row[4] if len(row) > 4 else ""
        
        if status == "Reviewed":
            # アーカイブ対象
            archived_row = list(row[:6]) + [now_str]
            rows_to_archive.append(archived_row)
        else:
            rows_to_keep.append(row)
    
    if not rows_to_archive:
        print("  アーカイブ対象の行がありません。")
        return 0
    
    # AI_Archiveに追加
    append_sheet(service, "AI_Archive", rows_to_archive)
    
    # AI_Analysisを未処理分だけに書き換え
    # まず全クリア
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range="AI_Analysis!A:F"
    ).execute()
    
    # ヘッダー + 残りのデータを書き戻し
    if rows_to_keep:
        write_sheet(service, "AI_Analysis", "A1", rows_to_keep)
    
    print(f"  {len(rows_to_archive)} 件をアーカイブしました。")
    return len(rows_to_archive)

# ==============================================================
# ヘルパー関数
# ==============================================================
def get_recent_lessons(service):
    """最近の教訓を取得"""
    data = read_sheet(service, "AI_Lessons")
    if len(data) < 2: return []
    
    # 最新5件
    recent = data[-5:]
    lessons = []
    for row in recent:
        if len(row) >= 3:
            text = str(row[2])
            if "教訓" in text:
                lessons.append(text)
    return lessons

def check_ollama():
    """Ollamaが起動しているか確認"""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            model_names = [m["name"] for m in models]
            print(f"  Ollama起動中。利用可能モデル: {model_names}")
            if not any(MODEL_NAME in name for name in model_names):
                print(f"  [WARN] '{MODEL_NAME}' が見つかりません。ollama pull {MODEL_NAME} を実行してください。")
                return False
            return True
    except:
        pass
    print("  [ERROR] Ollamaに接続できません。'ollama serve' で起動してください。")
    return False

# ==============================================================
# メイン実行
# ==============================================================
def main():
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    print(f"{'='*60}")
    print(f"ボートレースAI予測 (DeepSeek ローカル版)")
    print(f"実行時刻: {now.strftime('%Y-%m-%d %H:%M:%S')} JST")
    print(f"モデル: {MODEL_NAME}")
    print(f"{'='*60}", flush=True)
    
    # 1. Ollama接続確認
    print("\n--- Ollama接続確認 ---")
    if not check_ollama():
        print("\n[中止] Ollamaが起動していません。処理を中止します。")
        return
    
    # 2. Google Sheets接続
    print("\n--- Google Sheets接続 ---")
    try:
        service = get_sheets_service()
        print("  接続成功。")
    except Exception as e:
        print(f"  [ERROR] Google Sheets接続失敗: {e}")
        return
    
    start_time = time.time()
    
    # 3. 各フェーズ実行
    try:
        # Phase 3を先に実行（昨日の反省→新しい教訓をプロンプトに反映）
        run_review_cycle(service)
        
        # Phase 5: 反省済みをアーカイブ
        archive_predictions(service)
        
        # Phase 0: raw_race_data → features_daily 変換
        build_features_daily(service)
        
        # Phase 1: 今日のプロンプト生成
        generate_daily_prompts(service)
        
        # Phase 2: 予測実行（メイン処理、時間がかかる）
        predict_race_outcomes(service)
        
        # Phase 4: 選手成績更新
        update_racer_stats(service)
        
    except Exception as e:
        print(f"\n[ERROR] 処理中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
    
    elapsed = time.time() - start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    print(f"\n{'='*60}")
    print(f"全処理完了。所要時間: {hours}時間{minutes}分")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
