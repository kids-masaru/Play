import os
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# ユーザーから提供された情報で一時的に直接指定してテスト
LINE_CHANNEL_ACCESS_TOKEN = "uJR1siSzBnpHvHKcfFhisUHHeAd5j1bwO3/KN55GMBGOhSTTXxoI6sMAqjhIw47IfIkeux3A9ZDeUzmBDhL7e0+5ZHPq+MfEsZg+3aXlDRVnVWREoNoIeCzXUvBNCrXk4j1oagodSOxUxXA9g+9+DQdB04t89/1O/w1cDnyilFU="
LINE_USER_ID = "U501f6d44ef2185eae2f221347e9cb235"

def main():
    print("LINE Messaging API テスト送信を開始します...")
    line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    
    test_message = "🤖 [BoatRace AI] \nLINE連携が正常に完了しました！\n今後はこのアカウントから毎晩、明日の「AI推奨買い目」と「AI反省レポート」をお届けします！"
    
    try:
        line_bot_api.push_message(LINE_USER_ID, TextSendMessage(text=test_message))
        print("✅ 送信成功！スマホを確認してください。")
    except LineBotApiError as e:
        print(f"❌ 送信失敗: HTTP Status {e.status_code}")
        print(f"エラー詳細: {e.error.message}")
    except Exception as e:
        print(f"❌ 予期せぬエラー: {e}")

if __name__ == "__main__":
    main()
