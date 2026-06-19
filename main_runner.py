import os
import sys
import traceback
import subprocess
from datetime import datetime, timedelta, timezone
import pandas as pd

# 個別のローカル完結スクリプトをインポート
try:
    import local_collect_race_data
    import local_ai_pipeline
    import generate_dashboard_data
    import retrain_model
except ImportError as e:
    print(f"モジュールのインポートエラー: {e}")
    sys.exit(1)

def push_to_github():
    """ダッシュボードのデータをGitHubにプッシュする"""
    print("\n>>> GitHubへのデータ同期を開始します...")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    # ループ実験ログ JSON を生成（auto_research/results.tsv → loop_results.json）
    try:
        import generate_loop_data
        generate_loop_data.main()
    except Exception as e:
        print(f"  [WARN] generate_loop_data 失敗（無視して続行）: {e}")

    # 予測対戦ダッシュボードも結果込みで再生成（深夜に旧ダッシュボードと足並みを揃える）。
    # Gemini/学習Gemmaは朝バッチが生成するのでここでは叩かない(--skip)。push もしない(--no-push)＝
    # 下の git add/commit/push でまとめて公開する。
    try:
        subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "update_battle_dashboard.py"),
             "--skip-gemini", "--skip-gemma", "--no-push"],
            check=False, env=env,
        )
    except Exception as e:
        print(f"  [WARN] 予測対戦の再生成に失敗（無視して続行）: {e}")

    # 1. Add（夜バッチで更新されうるファイルをすべて追加）
    files_to_add = [
        "dashboard/public/daily_data/dashboard_data.json",
        "dashboard/public/daily_data/loop_results.json",
        "dashboard/public/daily_data/daily_odds_3t.csv",
        "dashboard/public/daily_data/daily_predictions.csv",
        "dashboard/public/daily_data/daily_reflections.csv",
        "dashboard/public/daily_data/daily_player_course_stats.csv",
        "daily_data/daily_odds_3t.csv",
        "daily_data/daily_reflections.csv",
        # 予測対戦（結果込み）の公開ファイル。深夜に旧ダッシュボードと同時更新するため追加。
        "dashboard/public/daily_data/daily_race_info.json",
        "dashboard/public/daily_data/ai_predictions_summary.json",
        "dashboard/public/daily_data/daily_history_results.csv",
        "dashboard/public/daily_data/daily_gemini_predictions.csv",
        "dashboard/public/daily_data/daily_gemma_predictions.csv",
    ]
    for f in files_to_add:
        if os.path.exists(f):
            try:
                subprocess.run(["git", "add", f], check=True, env=env)
            except subprocess.CalledProcessError as e:
                print(f"  [WARN] git add 失敗（続行）: {f} - {e}")

    # 2. Commit（nothing to commit は正常扱い。ローカル既存コミットがあれば push だけでも意味がある）
    commit_msg = f"Auto-update dashboard data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commit_result = subprocess.run(
        ["git", "commit", "-m", commit_msg, "--no-verify"],
        env=env, capture_output=True, text=True,
    )
    if commit_result.returncode == 0:
        print("  [INFO] 新規コミット作成済み")
    else:
        combined = (commit_result.stdout or "") + (commit_result.stderr or "")
        if "nothing to commit" in combined or "nothing added to commit" in combined:
            print("  [INFO] 今夜の新規コミット対象なし（既存のローカルコミットがあれば push します）")
        else:
            print(f"  [WARN] commit 失敗: {combined.strip()[:200]}")

    # 3. Push（commit の成否に関係なく、ローカルに溜まった既存コミットも押し出す）
    try:
        subprocess.run(["git", "push", "origin", "main"], check=True, env=env)
        print(">>> GitHubへの同期が完了しました。")
        return True
    except subprocess.CalledProcessError as e:
        print(f">>> push 失敗: {e}")
        return False
    except Exception as e:
        print(f">>> GitHub同期中に予期せぬエラー: {e}")
        return False

from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# ことちゃんRAG連携用（失敗してもメイン処理に影響しない）
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from utils.sheets_writer import write_daily_log
    _SHEETS_WRITER_AVAILABLE = True
except Exception as _e:
    print(f"[WARN] sheets_writer インポート失敗（無視して続行）: {_e}")
    _SHEETS_WRITER_AVAILABLE = False

# --- 設定 ---
# LINE Messaging API トークン（チャネルアクセストークン）
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
# LINE ユーザーID (送信先)
LINE_USER_ID = os.environ.get("LINE_USER_ID", "")

def send_line_message(message):
    """LINE Messaging APIを使ってスマホにメッセージを送信する"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        print("  [WARN] LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定のため、LINE通知をスキップしました。")
        return
        
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    
    try:
        line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=message))
        print("  [SUCCESS] LINEへ通知を送信しました。")
    except LineBotApiError as e:
        print(f"  [ERROR] LINE通知に失敗しました: {e.status_code} {e.error.message}")
    except Exception as e:
        print(f"  [ERROR] 予期せぬエラー: {e}")

def main():
    print(f"=== ボートレースAI 完全ローカル日次稼働システム 開始 ===")
    start_time = datetime.now()
    
    # 処理のステータス記録用
    report_blocks = [f"\n🤖 [BoatRace AI Report] {start_time.strftime('%Y/%m/%d')}\n日次処理が完了しました！"]

    # ことちゃんRAG連携用の集計変数
    _rag_predictions = ""
    _rag_results = ""
    _rag_profit = 0

    try:
        # 1. データ収集フェーズ
        print("\n--- [Phase 1] 日次データ収集 ---")
        local_collect_race_data.main()
        report_blocks.append("✅ データ収集 (公式Web -> CSV): 完了")
        
        # 2. 予測フェーズ & 反省会フェーズ
        print("\n--- [Phase 2 & 3] AI予測＆反省会 ---")
        local_ai_pipeline.main()
        report_blocks.append("✅ 予測＆反省: 完了")
        
        # 2.5. 週次1回（月曜日）にモデル再学習を実行
        JST_check = timezone(timedelta(hours=9))
        now_check = datetime.now(JST_check)
        if now_check.weekday() == 0:  # 0=月曜日
            print("\n--- [Phase 2.5] 週次モデル再学習 ---")
            try:
                retrain_model.main()
                report_blocks.append("✅ モデル再学習: 完了")
            except Exception as retrain_err:
                print(f"  [WARN] 再学習中にエラー: {retrain_err}")
                report_blocks.append(f"⚠️ モデル再学習: エラー発生")
        else:
            print(f"\n--- [Phase 2.5] モデル再学習: 月曜日のみ実行（今日は{['月','火','水','木','金','土','日'][now_check.weekday()]}曜日） ---")
        
        # 3. リサマリー（AI_Lessonsや今日の激アツ情報の抽出等）
        JST = timezone(timedelta(hours=9))
        now_jst = datetime.now(JST)
        if now_jst.hour >= 18:
            date_pred = (now_jst + timedelta(days=1)).strftime('%Y-%m-%d')
            date_refl = now_jst.strftime('%Y-%m-%d')
        else:
            date_pred = now_jst.strftime('%Y-%m-%d')
            date_refl = (now_jst - timedelta(days=1)).strftime('%Y-%m-%d')
            
        summary_text = ""
        pred_file = os.path.join("daily_data", "daily_predictions.csv")
        res_file = os.path.join("daily_data", "daily_history_results.csv")
        refl_file = os.path.join("daily_data", "daily_reflections.csv")
        
        # --- 1. 昨日の成績まとめと答え合わせ ---
        total_races = 0
        hits = 0
        total_invest = 0
        total_return = 0
        det_invest = 0
        det_return = 0
        det_hits = 0
        answer_check_lines = []
        
        if os.path.exists(pred_file) and os.path.exists(res_file):
            df_p = pd.read_csv(pred_file)
            df_r = pd.read_csv(res_file)
            
            y_preds = df_p[df_p['Date'].astype(str) == date_refl]
            y_res = df_r[df_r['Date'].astype(str) == date_refl]
            
            if not y_preds.empty and not y_res.empty:
                # 念のため重複IDを排除してからdictに変換する（再実行等によるCSV重複対策）
                y_res_unique = y_res.drop_duplicates(subset=['ID'], keep='last')
                res_dict = y_res_unique.set_index('ID')[['Result', 'Payout']].to_dict('index')
                
                for _, row in y_preds.iterrows():
                    rid = str(row['RaceID'])
                    if rid in res_dict:
                        total_races += 1
                        ans = str(res_dict[rid]['Result']).replace('-', '') # 例: 123
                        pay = 0
                        try:
                            pay = int(res_dict[rid]['Payout'])
                        except:
                            pass
                        
                        pred_str = str(row['Prediction'])
                        
                        # 予想から「最終推奨買い目」を抜き出す
                        import re
                        try:
                            buy_str = pred_str.split('■最終推奨買い目')[1].strip().replace('\n', ' ')
                        except:
                            buy_str = pred_str[-50:].replace('\n', ' ')
                            
                        # 簡易判定: 推奨買い目の中に結果が含まれているか
                        ans_dash = "-".join(list(ans))
                        is_hit = ans in buy_str or ans_dash in buy_str
                        
                        # Stakesカラムがあればケリー額を使用、なければ固定3000円にフォールバック
                        import json as _json
                        stakes_dict = {}
                        raw_stakes = row.get('Stakes', '') if 'Stakes' in row.index else ''
                        if raw_stakes and str(raw_stakes).strip() not in ('', 'nan'):
                            try:
                                stakes_dict = _json.loads(str(raw_stakes))
                            except Exception:
                                stakes_dict = {}

                        if stakes_dict:
                            race_invest = sum(stakes_dict.values())
                            hit_stake_units = stakes_dict.get(ans, 0) // 100
                        else:
                            tickets = set(re.findall(r'\d-\d-\d|\d{3}', buy_str))
                            num_tickets = len(tickets) if len(tickets) > 0 else 1
                            ticket_bet = (3000 // num_tickets // 100) * 100
                            race_invest = ticket_bet * num_tickets
                            hit_stake_units = ticket_bet // 100

                        total_invest += race_invest

                        if is_hit:
                            hits += 1
                            hit_return = pay * hit_stake_units
                            total_return += hit_return
                            res_mark = "🎯"
                            return_text = f"+{hit_return}円"
                        else:
                            res_mark = "❌"
                            return_text = "0円"

                        # Det版の集計（Stakes_Det カラムがあれば）
                        det_stakes_dict = {}
                        raw_det = row.get('Stakes_Det', '') if 'Stakes_Det' in row.index else ''
                        if raw_det and str(raw_det).strip() not in ('', 'nan', '{}'):
                            try:
                                det_stakes_dict = _json.loads(str(raw_det))
                            except Exception:
                                det_stakes_dict = {}
                        if det_stakes_dict:
                            det_invest += sum(det_stakes_dict.values())
                            det_hit_units = det_stakes_dict.get(ans, 0) // 100
                            if det_hit_units > 0:
                                det_hits += 1
                                det_return += pay * det_hit_units
                            
                        # LINE表示用に買い目と結果をフォーマット
                        buy_disp = buy_str[:15] + ("..." if len(buy_str) > 15 else "")
                        answer_check_lines.append(f"・{row['Venue']}{row['R']}R [{buy_disp}] -> 結果[{ans_dash}] {res_mark}(投資{race_invest}円/払戻{return_text})")
        
        if total_races > 0:
            hit_rate = (hits / total_races) * 100
            profit = total_return - total_invest
            profit_mark = "📈" if profit > 0 else "📉"
            roi = (total_return / total_invest) * 100 if total_invest > 0 else 0
            
            summary_text += f"\n\n📊 【昨日の成績】"
            summary_text += f"\n対象: {total_races}R中 {hits}R的中 ({hit_rate:.1f}%)"
            summary_text += f"\n投資額: {total_invest}円"
            summary_text += f"\n払戻額: {total_return}円"
            summary_text += f"\n収支: {profit_mark} {profit:+d}円 (回収率 {roi:.1f}%)"
            if det_invest > 0:
                det_profit = det_return - det_invest
                det_roi = det_return / det_invest * 100
                det_mark = "📈" if det_profit > 0 else "📉"
                summary_text += f"\n[Det版] 投資{det_invest}円/払戻{det_return}円 {det_mark}{det_profit:+d}円 (回収率 {det_roi:.1f}%)"
            elif 'Stakes_Det' in (df_p.columns if 'df_p' in dir() else []):
                summary_text += f"\n[Det版] 本日は買い目なし"
            # RAG用に結果・収支を記録
            _rag_results = f"{total_races}R中{hits}R的中({hit_rate:.1f}%) 投資{total_invest}円/払戻{total_return}円"
            _rag_profit = profit
            summary_text += f"\n\n=== 答え合わせ ==="
            for line in answer_check_lines:
                summary_text += f"\n{line}"
            summary_text += f"\n================="
            
        # --- 2. 昨日の反省 ---
        if os.path.exists(refl_file):
            df_refl = pd.read_csv(refl_file)
            target_refls = df_refl[df_refl['Date'].astype(str) == date_refl]
            if not target_refls.empty:
                summary_text += "\n\n📝 【それを踏まえたAI反省ハイライト(全件)】\n"
                for _, row in target_refls.iterrows():
                    lesson = str(row['Lesson']).replace('教訓:', '').replace('\n', ' ')[:50]
                    summary_text += f"「{lesson.strip()}...」\n"

        # --- 3. 今日の予測 ---
        if os.path.exists(pred_file):
            df_pred = pd.read_csv(pred_file)
            target_preds = df_pred[df_pred['Date'].astype(str) == date_pred]
            if not target_preds.empty:
                summary_text += "\n🔥 【本日の推奨買い目 (全件)】\n"
                summary_text += "※朝9時にEV強化版が配信されます\n"
                hot, normal, low = [], [], []
                for i, (_, row) in enumerate(target_preds.iterrows()):
                    pred_raw = str(row['Prediction'])
                    try:
                        rec = pred_raw.split('■最終推奨買い目')[1].strip()[:30].replace('\n', '')
                    except:
                        rec = pred_raw[-30:].replace('\n', '')

                    # EV情報がログに含まれていれば表示
                    log_raw = str(row.get('Log', ''))
                    ev_tag = ""
                    if 'MaxEV=' in log_raw:
                        import re as _re
                        ev_match = _re.search(r'MaxEV=([\d.]+)', log_raw)
                        if ev_match:
                            ev_val = float(ev_match.group(1))
                            ev_tag = f" (EV:{ev_val:.1f})" if ev_val > 0 else ""

                    line_str = f"📍 {row['Venue']}{row['R']}R: {rec}{ev_tag}"
                    if i < 3: hot.append(line_str)
                    elif i < 7: normal.append(line_str)
                    else: low.append(line_str)
                
                if hot:
                    summary_text += "\n[🔥激アツ]\n" + "\n".join(hot)
                if normal:
                    summary_text += "\n\n[✨普通]\n" + "\n".join(normal)
                if low:
                    summary_text += "\n\n[💨期待薄]\n" + "\n".join(low)
                summary_text += "\n"
                # RAG用に予想をまとめる
                all_preds = hot + normal + low
                _rag_predictions = " / ".join([p.replace("📍 ", "") for p in all_preds[:5]])
            else:
                summary_text += "\n\n🔥 【本日の推奨買い目】\n本日の対象レース（予測）はありません。"

        # --- 4. 回収率ダッシュボードの更新 ---
        print("\n--- [Phase 3.5] 回収率ダッシュボードデータ更新 ---")
        generate_dashboard_data.calculate_roi()
        
        # GitHubへプッシュ
        push_success = push_to_github()

        report_blocks.append("\n📈 【回収率ダッシュボード】更新完了")
        dashboard_url = "https://kids-masaru.github.io/Play/"
        report_blocks.append(f"詳細はこちら: {dashboard_url}")

        summary_text += f"\n※詳細はダッシュボードをご確認ください。\n{dashboard_url}"
        report_blocks.append(summary_text)
        
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"\n[FATAL ERROR] システムエラーが発生しました:\n{error_msg}")
        report_blocks.append(f"\n❌ エラー発生: 処理が中断されました。\n{e}")

    # LINE通知の実行
    final_message = "\n".join(report_blocks)
    print("\n--- [Phase 4] LINE通知送信 ---")
    send_line_message(final_message)

    # ことちゃんRAG連携：日次ログをGoogle Sheetsに書き込む
    if _SHEETS_WRITER_AVAILABLE:
        print("\n--- [Phase 5] ことちゃんRAG連携 ---")
        _rag_summary = (
            f"予想: {_rag_predictions or '記録なし'}\n"
            f"結果: {_rag_results or '記録なし'}\n"
            f"収支: {_rag_profit:+d}円"
        )
        write_daily_log(
            predictions=_rag_predictions,
            results=_rag_results,
            profit_loss=_rag_profit,
            summary=_rag_summary
        )

    end_time = datetime.now()
    duration = end_time - start_time
    print(f"=== 全工程完了 (所要時間: {duration}) ===")

if __name__ == "__main__":
    main()
