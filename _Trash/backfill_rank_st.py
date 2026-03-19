"""
バックフィルスクリプト: 過去データのRank/AvgST取得
=================================================
1月18日〜2月5日までの過去データを取得し、
Google SheetsのI列(Rank)とJ列(Avg ST)を埋めます。

使い方:
1. このスクリプトをローカルで実行するか、
2. GitHub Actionsで一度だけ実行します。

必要な環境変数:
- DRIVE_FOLDER_ID: SpreadsheetのID
- GDRIVE_API_KEY: サービスアカウントJSON
"""

import os
import json
import requests
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- Configuration ---
# ローカル実行時は環境変数がなければハードコードを使用
SPREADSHEET_ID = os.environ.get("DRIVE_FOLDER_ID") or "1G_qjAQBZBVMMOe7jxwhBUJtAEvZ4VAlhZaJRPu_O_ow"
SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_API_KEY")
REQUEST_TIMEOUT = 20

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 取得期間（ここを変更）
START_DATE = "20260118"  # 開始日
END_DATE = "20260205"    # 終了日

def get_sheets_service():
    if not SERVICE_ACCOUNT_JSON:
        raise ValueError("GDRIVE_API_KEY is not set.")
    creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

def fetch_url(url, retries=3):
    for i in range(retries + 1):
        try:
            resp = requests.get(url, headers=COMMON_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            return resp.text
        except Exception as e:
            if i < retries:
                print(f"  [Retry {i+1}] {e}")
                time.sleep(5)
            else:
                return None

def get_venues_for_date(target_date_str):
    url = f"https://www.boatrace.jp/owpc/pc/race/index?hd={target_date_str}"
    html = fetch_url(url)
    if not html: return []
    soup = BeautifulSoup(html, 'html.parser')
    venues = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if f"jcd=" in href and f"hd={target_date_str}" in href:
            try:
                query = href.split('?')[-1]
                params = dict(x.split('=') for x in query.split('&'))
                if 'jcd' in params:
                    venues.add(params['jcd'])
            except:
                continue
    return sorted(list(venues))

def scrape_rank_st(jcd, rno, date_str):
    """選手のRankとAvg STだけを取得"""
    url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno={rno}&jcd={jcd}&hd={date_str}"
    html = fetch_url(url)
    if not html: return {}
    
    venue_map = { "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国", "11": "びわこ", "12": "住之江", "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島", "17": "宮島", "18": "徳山", "19": "下関", "20": "若松", "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村" }
    venue_name = venue_map.get(jcd, f"Venue_{jcd}")
    race_id = f"{date_str}_{venue_name}_{rno}"
    
    result = {}  # {player_id: {"rank": "A1", "st": "0.15"}}
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        tbodies = soup.find_all('tbody')
        
        for tbody in tbodies:
            boat_td = tbody.find('td', class_=re.compile(r'is-boatColor\d'))
            if not boat_td: continue
            
            # Get lane
            try:
                classes = " ".join(boat_td.get('class', []))
                match = re.search(r'is-boatColor(\d)', classes)
                lane = int(match.group(1)) if match else 0
            except:
                continue
            
            # Player ID and Rank
            player_id = ""
            racer_rank = ""
            
            fs11_divs = tbody.find_all('div', class_=lambda x: x and 'is-fs11' in x)
            for div in fs11_divs:
                text = div.get_text(strip=True)
                parts = re.split(r'[/／]', text)
                if len(parts) >= 1 and parts[0].strip().isdigit():
                    player_id = parts[0].strip()
                    if len(parts) >= 2:
                        rank_candidate = parts[1].strip().upper()
                        if rank_candidate in ["A1", "A2", "B1", "B2"]:
                            racer_rank = rank_candidate
                    break
            
            # Average ST
            avg_st = ""
            tds = tbody.find_all('td')
            for td in tds:
                td_text = td.get_text(strip=True)
                if re.match(r'^0\.\d{2}$', td_text):
                    avg_st = td_text
                    break
            
            if player_id:
                result[f"{race_id}_{lane}"] = {"rank": racer_rank, "st": avg_st, "player_id": player_id}
    
    except Exception as e:
        print(f"  Error: {e}")
    
    return result

def main():
    print("=" * 50)
    print("バックフィル開始: 過去データのRank/AvgST取得")
    print(f"期間: {START_DATE} 〜 {END_DATE}")
    print("=" * 50)
    
    service = get_sheets_service()
    
    # 既存データを読み込み
    print("\n[Step 1] 既存データ読み込み中...")
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range='raw_results!A:K'
    ).execute()
    existing_rows = result.get('values', [])
    print(f"  既存データ: {len(existing_rows)} 行")
    
    # 日付でループ
    current = datetime.strptime(START_DATE, "%Y%m%d")
    end = datetime.strptime(END_DATE, "%Y%m%d")
    
    all_scraped = {}
    
    print("\n[Step 2] 過去データをスクレイピング中...")
    while current <= end:
        date_str = current.strftime("%Y%m%d")
        print(f"\n  日付: {date_str}")
        
        venues = get_venues_for_date(date_str)
        if not venues:
            print(f"    レースなし")
            current += timedelta(days=1)
            continue
        
        for jcd in venues:
            print(f"    会場: {jcd}", end=" ")
            for rno in range(1, 13):
                time.sleep(0.3)  # レート制限対策
                scraped = scrape_rank_st(jcd, rno, date_str)
                all_scraped.update(scraped)
            print(f"({len(all_scraped)} 件取得済み)")
        
        current += timedelta(days=1)
    
    print(f"\n[Step 3] スクレイピング完了: 計 {len(all_scraped)} 件")
    
    # 既存データを更新
    print("\n[Step 4] データ更新中...")
    updates = []
    
    for i, row in enumerate(existing_rows):
        if i == 0: continue  # ヘッダースキップ
        if len(row) < 6: continue
        
        # race_id + lane で検索キーを作成
        # シート上のRaceID形式: "20260205_桐生_4" 
        try:
            race_id = row[3]  # D列 (例: 20260205_桐生_4)
            lane = row[4]     # E列 (例: 1)
            
            # スクレイピングデータのキー形式に合わせる
            key = f"{race_id}_{lane}"
            
            if key in all_scraped:
                data = all_scraped[key]
                # I列(index 8)とJ列(index 9)を更新
                # 既に値がある場合はスキップ
                if len(row) >= 10 and row[8] and row[9]:
                    continue
                
                updates.append({
                    "range": f"raw_results!I{i+1}:J{i+1}",
                    "values": [[data["rank"], data["st"]]]
                })
        except Exception as e:
            continue
    
    print(f"  更新対象: {len(updates)} 件")
    
    # バッチ更新
    if updates:
        print("\n[Step 5] スプレッドシートに書き込み中...")
        batch_size = 100
        for i in range(0, len(updates), batch_size):
            batch = updates[i:i+batch_size]
            body = {"valueInputOption": "RAW", "data": batch}
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=SPREADSHEET_ID,
                body=body
            ).execute()
            print(f"  {min(i+batch_size, len(updates))}/{len(updates)} 件完了")
            time.sleep(1)
        
        print("\n✅ バックフィル完了！")
    else:
        print("\n⚠️ 更新対象データがありませんでした")

if __name__ == "__main__":
    main()
