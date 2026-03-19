"""古いデータのクリーンアップ: AI_Analysis + features_daily"""
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

f = open('boatraceauto-b2bfa32e72bc.json', 'r')
d = json.load(f)
f.close()
creds = service_account.Credentials.from_service_account_info(d, scopes=['https://www.googleapis.com/auth/spreadsheets'])
svc = build('sheets', 'v4', credentials=creds)
sid = '1ixdf0Ep4DWSYPPED0xwCqwuG0U-aRSyl_5JI801Jk4Q'

# 1. AI_Analysis をクリア（ヘッダーだけ残す）
print("=== AI_Analysis クリア ===")
aa = svc.spreadsheets().values().get(spreadsheetId=sid, range='AI_Analysis').execute().get('values', [])
print(f"  現在: {len(aa)} rows")
if len(aa) > 1:
    svc.spreadsheets().values().clear(spreadsheetId=sid, range='AI_Analysis!A2:Z').execute()
    print("  古いデータを削除しました。ヘッダーのみ残っています。")

# 2. features_daily のテンプレート行を削除して再構築
print("\n=== features_daily クリア ===")
fd = svc.spreadsheets().values().get(spreadsheetId=sid, range='features_daily').execute().get('values', [])
print(f"  現在: {len(fd)} rows")
if len(fd) > 1:
    svc.spreadsheets().values().clear(spreadsheetId=sid, range='features_daily!A2:Z').execute()
    print("  古いデータを削除しました。ヘッダーのみ残っています。")
    print("  → predict_with_deepseek.py のPhase 0が再生成します。")

# 3. AI_Lessons もクリア (古い文字化けデータ)
print("\n=== AI_Lessons クリア ===")
al = svc.spreadsheets().values().get(spreadsheetId=sid, range='AI_Lessons').execute().get('values', [])
print(f"  現在: {len(al)} rows")
if len(al) > 1:
    svc.spreadsheets().values().clear(spreadsheetId=sid, range='AI_Lessons!A2:Z').execute()
    print("  古いデータを削除しました。")

print("\n=== 完了 ===")
print("次に 'python predict_with_deepseek.py' を実行してください！")
