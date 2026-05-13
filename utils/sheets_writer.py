"""
KOTO_CONFIGスプレッドシートのBOATRACE_LOGシートに日次データを書き込むユーティリティ。
"""
import os
import json
from datetime import datetime, timezone

# KOTO_CONFIGスプレッドシートID（kotoシステムと共有）
KOTO_CONFIG_SPREADSHEET_ID = "14H7nHAkO8tpawg_pcSLqOQwrv8Y0LzY2lSLIFGfLR6o"
BOATRACE_LOG_SHEET = "BOATRACE_LOG"

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# このファイルからの相対パスでサービスアカウントJSONを参照
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_ACCOUNT_FILE = os.path.join(_BASE_DIR, "boatraceauto-b2bfa32e72bc.json")


def _get_sheets_service():
    """Google Sheets APIサービスを取得する"""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build('sheets', 'v4', credentials=creds)


def _ensure_sheet_exists(service):
    """BOATRACE_LOGシートが存在しない場合は作成してヘッダー行を追加する。失敗時は例外を上げて呼び出し元のtry/exceptに任せる"""
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=KOTO_CONFIG_SPREADSHEET_ID
    ).execute()

    sheet_names = [s['properties']['title'] for s in spreadsheet.get('sheets', [])]
    if BOATRACE_LOG_SHEET in sheet_names:
        return

    # シートを新規作成
    service.spreadsheets().batchUpdate(
        spreadsheetId=KOTO_CONFIG_SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": BOATRACE_LOG_SHEET}}}]}
    ).execute()

    # ヘッダー行を追加
    service.spreadsheets().values().append(
        spreadsheetId=KOTO_CONFIG_SPREADSHEET_ID,
        range=f"{BOATRACE_LOG_SHEET}!A1",
        valueInputOption="RAW",
        body={"values": [["date", "predictions", "results", "profit_loss", "summary", "ingested"]]}
    ).execute()
    print(f"[SheetsWriter] {BOATRACE_LOG_SHEET} シートを作成しました")


def write_daily_log(predictions: str, results: str, profit_loss: int, summary: str):
    """
    日次ボートレースログをBOATRACE_LOGシートに書き込む。

    Args:
        predictions: 予想内容の文字列（例: "桐生3R 1-3-2 / 戸田5R 2-1-4"）
        results: 結果の文字列（例: "桐生3R 的中 / 戸田5R 外れ"）
        profit_loss: 収支（円）（例: 2400 または -1200）
        summary: 1〜3行の日本語サマリー
    """
    try:
        service = _get_sheets_service()
        _ensure_sheet_exists(service)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        row = [today, predictions, results, profit_loss, summary, "FALSE"]

        service.spreadsheets().values().append(
            spreadsheetId=KOTO_CONFIG_SPREADSHEET_ID,
            range=f"{BOATRACE_LOG_SHEET}!A1",
            valueInputOption="RAW",
            body={"values": [row]}
        ).execute()
        print(f"[SheetsWriter] BOATRACE_LOG に書き込みました: {today}")

    except Exception as e:
        # Sheets書き込み失敗してもメイン処理に影響しない
        print(f"[SheetsWriter] 書き込み失敗（無視して続行）: {e}")
