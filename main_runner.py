import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
import pandas as pd

# 個別のローカル完結スクリプトをインポート
try:
    import local_collect_race_data
    import local_ai_pipeline
    import generate_dashboard_data
except ImportError as e:
    print(f"モジュールのインポートエラー: {e}")
    sys.exit(1)

from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

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

    try:
        # 1. データ収集フェーズ
        print("\n--- [Phase 1] 日次データ収集 ---")
        local_collect_race_data.main()
        report_blocks.append("✅ データ収集 (公式Web -> CSV): 完了")
        
        # 2. 予測フェーズ & 反省会フェーズ
        print("\n--- [Phase 2 & 3] AI予測＆反省会 ---")
        local_ai_pipeline.main()
        report_blocks.append("✅ 予測＆反省: 完了")
        
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
                        
                        # 買い目点数の解析
                        tickets = set(re.findall(r'\d-\d-\d|\d{3}', buy_str))
                        num_tickets = len(tickets) if len(tickets) > 0 else 1
                        
                        # 「1レース3000円投資」の均等配分（100円単位）
                        ticket_bet = (3000 // num_tickets // 100) * 100
                        race_invest = ticket_bet * num_tickets
                        total_invest += race_invest
                        
                        if is_hit:
                            hits += 1
                            hit_return = pay * (ticket_bet // 100)
                            total_return += hit_return
                            res_mark = "🎯"
                            return_text = f"+{hit_return}円"
                        else:
                            res_mark = "❌"
                            return_text = "0円"
                            
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
                hot, normal, low = [], [], []
                for i, (_, row) in enumerate(target_preds.iterrows()):
                    pred_raw = str(row['Prediction'])
                    try:
                        rec = pred_raw.split('■最終推奨買い目')[1].strip()[:30].replace('\n', '')
                    except:
                        rec = pred_raw[-30:].replace('\n', '')
                    line_str = f"📍 {row['Venue']}{row['R']}R: {rec}"
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
            else:
                summary_text += "\n\n🔥 【本日の推奨買い目】\n本日の対象レース（予測）はありません。"

        # --- 4. 回収率ダッシュボードの更新 ---
        print("\n--- [Phase 3.5] 回収率ダッシュボードデータ更新 ---")
        generate_dashboard_data.calculate_roi()
        report_blocks.append("\n📈 【回収率ダッシュボード】更新完了")
        report_blocks.append("詳細はこちら: http://localhost:5173")

        summary_text += f"\n※詳細はPC内の daily_data フォルダ、またはダッシュボードをご確認ください。"
        report_blocks.append(summary_text)
        
    except Exception as e:
        error_msg = traceback.format_exc()
        print(f"\n[FATAL ERROR] システムエラーが発生しました:\n{error_msg}")
        report_blocks.append(f"\n❌ エラー発生: 処理が中断されました。\n{e}")

    # LINE通知の実行
    final_message = "\n".join(report_blocks)
    print("\n--- [Phase 4] LINE通知送信 ---")
    send_line_message(final_message)
    
    end_time = datetime.now()
    duration = end_time - start_time
    print(f"=== 全工程完了 (所要時間: {duration}) ===")

if __name__ == "__main__":
    main()
