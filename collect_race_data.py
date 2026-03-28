import os
import json
import requests
import time
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
from google.oauth2 import service_account
from googleapiclient.discovery import build
import csv

# --- Configuration ---
# Spreadsheet ID for 'features_daily' (Analysis Sheet)
SPREADSHEET_ID = os.environ.get("TARGET_SPREADSHEET_ID") or "1BeQNQqhwsby9Y3wTemsfmlSVXyMZKlBcuR1OQ_X_bsk"
REQUEST_TIMEOUT = 20  # seconds

# Try loading from local file first (for easy local execution), then env var
json_path = "boatraceauto-b2bfa32e72bc.json"
if os.path.exists(json_path):
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            SERVICE_ACCOUNT_JSON = f.read()
        print(f"Loaded credentials from {json_path}")
    except Exception as e:
        print(f"Error reading {json_path}: {e}")
        SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_API_KEY")
else:
    SERVICE_ACCOUNT_JSON = os.environ.get("GDRIVE_API_KEY")


COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_sheets_service():
    if not SERVICE_ACCOUNT_JSON:
        raise ValueError("Environment variable GDRIVE_API_KEY is not set.")
    creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
    print(f"--- DEBUG: Using Service Account Email: {creds_dict.get('client_email')} ---", flush=True)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

def fetch_url(url, retries=3, session=None):
    """Robust fetch with timeout and retries."""
    requester = session if session else requests
    for i in range(retries + 1):
        try:
            resp = requester.get(url, headers=COMMON_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            # ボートレース公式サイトはUTF-8 (Content-Type: text/html;charset=UTF-8)
            if 'boatrace.jp' in url:
                resp.encoding = 'utf-8'
            else:
                resp.encoding = resp.apparent_encoding
            return resp.text
        except requests.exceptions.RequestException as e:
            if i < retries:
                print(f"    [Retry {i+1}/{retries}] Warning: {e}. Waiting 5s...")
                time.sleep(5)
            else:
                print(f"    [Error] Failed to fetch {url}. {e}")
                return None


# --- セッション管理（オッズページ等、Cookie必須のページ用）---
_boatrace_session = None

def get_boatrace_session():
    """boatrace.jp用のセッションを取得する（Cookie必須ページ用）。
    オッズページはセッションCookieがないと正しい値を返さないため、
    最初にインデックスページにアクセスしてCookieを取得する。
    """
    global _boatrace_session
    if _boatrace_session is not None:
        return _boatrace_session

    _boatrace_session = requests.Session()
    _boatrace_session.headers.update(COMMON_HEADERS)

    # インデックスページにアクセスしてCookieを取得
    try:
        _boatrace_session.get("https://www.boatrace.jp/owpc/pc/race/index", timeout=REQUEST_TIMEOUT)
    except Exception:
        pass  # Cookie取得失敗でもセッション自体は返す

    return _boatrace_session

def get_venues_for_date(target_date_str):
    url = f"https://www.boatrace.jp/owpc/pc/race/index?hd={target_date_str}"
    print(f"Fetching Index for {target_date_str}")
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

# --- 会場名マッピング (共通) ---
VENUE_MAP = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川",
    "06": "浜名湖", "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国",
    "11": "びわこ", "12": "住之江", "13": "尼崎", "14": "鳴門", "15": "丸亀",
    "16": "児島", "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村"
}

# --- ヘッダー定義 ---
RAW_RACE_DATA_HEADERS = ["Date", "Venue", "R", "ID", "Lane", "PlayerID", "Name", "Motor", "Rank", "WinRate", "Count"]
HISTORY_RESULTS_HEADERS = ["Date", "Venue", "R", "ID", "Result", "Payout"]
RAW_BEFOREINFO_HEADERS = ["ID", "Date", "Venue", "R", "Weather", "WindSpeed", "WindDir", "Wave", "WaterTemp",
                          "B1_Weight", "B1_Tilt", "B1_ExTime", "B2_Weight", "B2_Tilt", "B2_ExTime",
                          "B3_Weight", "B3_Tilt", "B3_ExTime", "B4_Weight", "B4_Tilt", "B4_ExTime",
                          "B5_Weight", "B5_Tilt", "B5_ExTime", "B6_Weight", "B6_Tilt", "B6_ExTime"]
PLAYER_COURSE_STATS_HEADERS = ["PlayerID", "C1_Win", "C1_2in", "C1_3in", "C2_Win", "C2_2in", "C2_3in",
                               "C3_Win", "C3_2in", "C3_3in", "C4_Win", "C4_2in", "C4_3in",
                               "C5_Win", "C5_2in", "C5_3in", "C6_Win", "C6_2in", "C6_3in"]
ODDS_3T_HEADERS = ["ID", "Date", "Venue", "R", "Combination", "Odds"]

def append_to_csv(filename, headers, rows):
    """データをCSVファイルに追記する。ファイルが無い場合はヘッダー付きで新規作成。"""
    if not rows: return
    file_exists = os.path.isfile(filename)
    with open(filename, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(headers)
        writer.writerows(rows)

def ensure_headers(service, spreadsheet_id, sheet_name, headers):
    """シートが空の場合、ヘッダーを自動挿入する。"""
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A1:A1'
        ).execute()
        values = result.get('values', [])
        if not values or not values[0] or not values[0][0]:
            print(f"  [Header] '{sheet_name}' is empty. Inserting headers...", flush=True)
            service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A1',
                valueInputOption='RAW', body={'values': [headers]}
            ).execute()
            print(f"  [Header] Done.", flush=True)
        else:
            print(f"  [Header] '{sheet_name}' already has data (A1='{values[0][0]}').", flush=True)
    except Exception as e:
        print(f"  [Header] Warning: Could not check/insert headers for '{sheet_name}': {e}", flush=True)

# --- Part 1: Today's Race Program (Enhanced with Rank & Avg ST) ---
def scrape_program(jcd, rno, date_str):
    url = f"https://www.boatrace.jp/owpc/pc/race/racelist?rno={rno}&jcd={jcd}&hd={date_str}"
    html = fetch_url(url)
    if not html:
        print(f"[WARN] fetch_url returned None for {jcd} R{rno}", flush=True)
        return []
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        venue_name = VENUE_MAP.get(jcd, f"Venue_{jcd}")
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        rows = []
        tbodies = soup.find_all('tbody')
        boat_count = 0
        for tbody in tbodies:
            tds = tbody.find_all('td')
            boat_td = tbody.find('td', class_=re.compile(r'is-boatColor\d'))
            if not boat_td: continue
            boat_count += 1
            try:
                classes = " ".join(boat_td.get('class', []))
                match = re.search(r'is-boatColor(\d)', classes)
                lane = int(match.group(1)) if match else 0
            except: continue
            
            # Player Name
            name_div = tbody.find('div', class_=lambda x: x and 'is-fs18' in x and 'is-fBold' in x)
            name = name_div.text.strip().replace("\u3000", "") if name_div else "Unknown"
            
            # Player ID and Rank/Class
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
            
            # 全国勝率
            win_rate = ""
            for td in tds:
                td_text = td.get_text(" ", strip=True)
                tokens = td_text.split()
                found = False
                for token in tokens:
                    if re.match(r'^[1-9]\.\d{2}$', token):
                        win_rate = token
                        found = True
                        break
                if found:
                    break
            
            # Motor number
            motor_no = 0
            if len(tds) >= 7:
                txt = tds[6].get_text(" ", strip=True).split()[0]
                if txt.isdigit(): motor_no = int(txt)
            
            race_id = f"{date_str}_{venue_name}_{rno}"
            row = [display_date, venue_name, rno, race_id, lane, player_id, name, motor_no, racer_rank, win_rate, 6]
            rows.append(row)
        
        if boat_count == 0 and len(tbodies) > 0:
            print(f"[DEBUG] {jcd} R{rno}: {len(tbodies)} tbodies but 0 boats found (is-boatColor missing?)", flush=True)
        
        return rows
    except Exception as e:
        print(f"    Error scraping Program {jcd} R{rno}: {e}", flush=True)
        return []

# --- Part 2: Yesterday's Results ---
def scrape_result_venue(jcd, date_str):
    url = f"https://www.boatrace.jp/owpc/pc/race/resultlist?jcd={jcd}&hd={date_str}"
    html = fetch_url(url)
    if not html: return []
    results = []
    try:
        soup = BeautifulSoup(html, 'html.parser')
        venue_name = VENUE_MAP.get(jcd, f"Venue_{jcd}")
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        target_table = None
        for tbl in soup.find_all('table'):
            if "3連勝単式" in tbl.get_text():
                target_table = tbl
                break
        if target_table:
            rows = target_table.find_all('tr')
            for row in rows:
                tds = row.find_all('td')
                if not tds: continue
                rno_text = tds[0].get_text(strip=True)
                if not rno_text.endswith("R"): continue
                try: rno = int(rno_text.replace("R", ""))
                except: continue
                combo_text = ""
                combo_div = row.find(class_="numberSet1_row")
                if combo_div:
                    nums = [s.get_text(strip=True) for s in combo_div.find_all(class_=re.compile(r'numberSet1_number'))]
                    if nums: combo_text = "-".join(nums)
                    else: combo_text = combo_div.get_text(strip=True)
                else: combo_text = tds[1].get_text(strip=True)
                payout_text = tds[2].get_text(strip=True).replace("¥", "").replace(",", "").replace("円", "")
                if combo_text and payout_text:
                    race_id = f"{date_str}_{venue_name}_{rno}"
                    results.append([display_date, venue_name, rno, race_id, combo_text, payout_text])
        return results
    except Exception as e:
        print(f"    Error scraping Result List {jcd}: {e}")
        return []

# --- Part 3: Yesterday's Before Info (New!) ---
def scrape_beforeinfo(jcd, rno, date_str):
    url = f"https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={rno}&jcd={jcd}&hd={date_str}"
    
    html = fetch_url(url)
    if not html: return []
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        venue_name = VENUE_MAP.get(jcd, f"Venue_{jcd}")
        display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        race_id = f"{date_str}_{venue_name}_{rno}"
        
        # Weather
        weather = ""
        wind_dir = ""
        wind_speed = ""
        wave = ""
        water_temp = ""
        
        weather_section = soup.find(class_="weather1_body")
        if weather_section:
            units = weather_section.find_all(class_="weather1_bodyUnit")
            for unit in units:
                label = unit.find(class_="weather1_bodyUnitLabel")
                data = unit.find(class_="weather1_bodyUnitLabelData")
                if not label: continue
                
                lbl_text = label.get_text(strip=True)
                val_text = data.get_text(strip=True) if data else ""
                
                if "天候" in lbl_text: weather = val_text
                if "風速" in lbl_text: wind_speed = val_text
                if "波高" in lbl_text: wave = val_text
                if "水温" in lbl_text: water_temp = val_text
                
                if "風向" in lbl_text:
                     img = unit.find("img")
                     if img:
                         classes = img.get("class", [])
                         for c in classes:
                             if c.startswith("is-wind"):
                                 wind_dir = c.replace("is-wind", "")

        # Boat Info
        boats_data = [""] * 18 # 6 boats * 3 data points
        tables = soup.find_all("table")
        target_src = None
        for t in tables:
            if "展示タイム" in t.get_text():
                target_src = t
                break
        
        if target_src:
            tbodies = target_src.find_all("tbody")
            for i, tbody in enumerate(tbodies[:6]):
                tr = tbody.find("tr")
                if not tr: continue
                tds = tr.find_all("td")
                # Weight: nth-child(4) [idx 3], Exhibition: nth-child(5) [idx 4], Tilt: nth-child(6) [idx 5]
                if len(tds) >= 6:
                    w = tds[3].get_text(strip=True)
                    t = tds[4].get_text(strip=True) 
                    ti = tds[5].get_text(strip=True)
                    base_idx = i * 3
                    boats_data[base_idx] = w
                    boats_data[base_idx+1] = ti
                    boats_data[base_idx+2] = t

        row = [race_id, display_date, venue_name, rno, weather, wind_speed, wind_dir, wave, water_temp] + boats_data
        return [row]

    except Exception as e:
        return []

def scrape_player_course_stats(player_id):
    """選手のコース別3連対率を取得する。"""
    url = f"https://www.boatrace.jp/owpc/pc/data/racersearch/course?toban={player_id}"
    html = fetch_url(url)
    if not html: return None
    
    try:
        soup = BeautifulSoup(html, 'html.parser')
        # 「コース別3連対率」のテーブルを探す
        target_table = None
        for table in soup.find_all('table', class_='is-w400'):
            if "コース別3連対率" in table.get_text():
                target_table = table
                break
        
        if not target_table: return None
        
        # 1コース〜6コースのデータを格納 (Win, 2in, 3in)
        stats = []
        rows = target_table.find_all('tbody') # 現行サイトは tr がひとつずつ tbody で囲まれている
        for tbody in rows[:6]:
            bars = tbody.find_all('span', class_='is-progress')
            # bars[0]:1着率, bars[1]:2着率, bars[2]:3着率 (累積ではなく個別の場合があるが、widthで判定)
            # サイト構造的に、累積バーになっている場合は style="width: XX%" の値を取得
            course_data = []
            for bar in bars[:3]:
                style = bar.get('style', '')
                match = re.search(r'width:\s*([\d.]+)%', style)
                val = float(match.group(1)) if match else 0.0
                course_data.append(val)
            
            # サイト上の「3連対率」ラベルも念のため確認 (もし個別率が取れなかった時のバックアップ等)
            # 現状は width から 1着, 2着内, 3着内 を算出するロジックにする
            # 実際はバーが重なっているので、1個目が1着率、2個目が2着内率(1+2)、3個目が3着内率(1+2+3)
            # これを個別に直すか、そのまま使うかは後続の判断だが、ここでは取得した累積値をそのまま入れる
            stats.extend(course_data)
        
        if len(stats) < 18:
            # 足りない分を0埋め
            stats += [0.0] * (18 - len(stats))
            
        return [str(player_id)] + [str(s) for s in stats]
    except Exception as e:
        print(f"Error scraping Course Stats for {player_id}: {e}")
        return None

def scrape_motor_stats(jcd, date_str):
    """指定会場のモーター成績一覧を取得する。

    URL: https://www.boatrace.jp/owpc/pc/race/motorlist?jcd={jcd}&hd={date_str}

    Returns:
        list of [venue_name, motor_no, win_rate, top2_rate, top3_rate, date_str]
        取得失敗時は空リスト
    """
    url = f"https://www.boatrace.jp/owpc/pc/race/motorlist?jcd={jcd}&hd={date_str}"
    html = fetch_url(url)
    if not html:
        return []

    venue_name = VENUE_MAP.get(jcd, jcd)
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    results = []

    try:
        soup = BeautifulSoup(html, 'html.parser')
        # モーター成績テーブルを検索
        table = soup.find('table', class_='is-w495')
        if not table:
            # フォールバック: 別のテーブル構造を試す
            tables = soup.find_all('table')
            for t in tables:
                if 'モーター' in t.get_text()[:100]:
                    table = t
                    break

        if not table:
            return []

        rows = table.find_all('tr')
        for row in rows[1:]:  # ヘッダーをスキップ
            cells = row.find_all('td')
            if len(cells) < 4:
                continue

            try:
                motor_no = cells[0].get_text(strip=True)
                if not motor_no or not motor_no.isdigit():
                    continue

                # 2連率は一般的に4列目あたりにある
                # サイト構造: モーター番号 | 勝率 | 2連率 | 3連率 (会場によって列数が異なる場合あり)
                win_rate = 0.0
                top2_rate = 0.0
                top3_rate = 0.0

                for i, cell in enumerate(cells[1:], 1):
                    text = cell.get_text(strip=True)
                    # 数値を含むセルを探す
                    try:
                        val = float(text.replace('%', ''))
                        if i == 1:
                            win_rate = val
                        elif i == 2:
                            top2_rate = val
                        elif i == 3:
                            top3_rate = val
                            break
                    except ValueError:
                        continue

                results.append([venue_name, motor_no, win_rate, top2_rate, top3_rate, display_date])
            except Exception:
                continue

    except Exception as e:
        print(f"Error scraping motor stats for {venue_name}: {e}")

    return results


MOTOR_STATS_HEADERS = ["Venue", "MotorNo", "WinRate", "Top2Rate", "Top3Rate", "UpdatedDate"]


def scrape_odds_3t(jcd, rno, date_str):
    """3連単オッズ（全120通り）をPlaywrightで取得する。

    boatrace.jpのオッズページはJavaScriptで動的にオッズ値を注入するため、
    requestsベースの静的スクレイピングでは取得できない。
    Playwrightでヘッドレスブラウザを使い、JSレンダリング後のDOMからオッズを抽出する。

    Returns:
        list of [race_id, display_date, venue_name, rno, combination, odds] の120行
        （取得失敗時は空リスト）
    """
    venue_name = VENUE_MAP.get(jcd, f"Venue_{jcd}")
    display_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    race_id = f"{date_str}_{venue_name}_{rno}"

    # 既知の組み合わせ順序を生成
    def get_combos_for_first(first):
        others = [b for b in range(1, 7) if b != first]
        combos = []
        for second in others:
            thirds = [b for b in range(1, 7) if b != first and b != second]
            for third in thirds:
                combos.append((first, second, third))
        return combos

    block_combos = [get_combos_for_first(f) for f in range(1, 7)]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("    [ERROR] playwrightがインストールされていません。pip install playwright && playwright install chromium")
        return []

    try:
        # グローバルブラウザインスタンスを使用（_odds_browserが存在すれば再利用）
        page = _get_odds_page()

        url = f"https://www.boatrace.jp/owpc/pc/race/odds3t?rno={rno}&jcd={jcd}&hd={date_str}"
        page.goto(url, wait_until='domcontentloaded', timeout=30000)

        # JSがオッズを注入するのを待つ（最大6秒、0.5秒刻み）
        for _ in range(12):
            time.sleep(0.5)
            cells = page.query_selector_all('td.oddsPoint')
            if cells:
                # 少なくとも1つの非ゼロ値があるか確認
                sample = cells[len(cells)//2].inner_text().strip()
                if sample and sample != '0.0':
                    break

        cells = page.query_selector_all('td.oddsPoint')
        if not cells:
            return []

        # 120セルの値を抽出
        rows_data = []
        for row_idx in range(20):
            for block_idx in range(6):
                cell_idx = row_idx * 6 + block_idx
                if cell_idx >= len(cells):
                    continue

                odds_text = cells[cell_idx].inner_text().strip()
                try:
                    odds_val = float(odds_text)
                except (ValueError, TypeError):
                    odds_val = 0.0

                combo = block_combos[block_idx][row_idx]
                combo_str = f"{combo[0]}-{combo[1]}-{combo[2]}"
                rows_data.append([race_id, display_date, venue_name, rno, combo_str, odds_val])

        return rows_data

    except Exception as e:
        print(f"    Error scraping Odds3T {jcd} R{rno}: {e}", flush=True)
        return []


# --- Playwright ブラウザ管理（オッズ取得用） ---
_odds_playwright = None
_odds_browser = None
_odds_page = None

def _get_odds_page():
    """オッズ取得用のPlaywrightページを取得（再利用可能）"""
    global _odds_playwright, _odds_browser, _odds_page
    if _odds_page is not None:
        return _odds_page

    from playwright.sync_api import sync_playwright
    _odds_playwright = sync_playwright().start()
    _odds_browser = _odds_playwright.chromium.launch(headless=True)
    _odds_page = _odds_browser.new_page()
    return _odds_page

def close_odds_browser():
    """オッズ取得用のブラウザを明示的に閉じる"""
    global _odds_playwright, _odds_browser, _odds_page
    if _odds_browser:
        try:
            _odds_browser.close()
        except:
            pass
    if _odds_playwright:
        try:
            _odds_playwright.stop()
        except:
            pass
    _odds_playwright = None
    _odds_browser = None
    _odds_page = None


def debug_print_sheet_names(service, ssid):
    try:
        ss = service.spreadsheets().get(spreadsheetId=ssid).execute()
        print(f"--- DEBUG: Sheet Names in {ssid} ---", flush=True)
        for s in ss.get('sheets', []):
            print(f"  - '{s['properties']['title']}'", flush=True)
        print("---------------------------------------------", flush=True)
    except Exception as e:
        print(f"DEBUG FAIL: Could not list sheets: {e}", flush=True)

def batch_upload(service, spreadsheet_id, sheet_name, all_rows, batch_size=100):
    """データを小分けにしてGoogle Sheetsにアップロードする。Broken pipe対策。"""
    total = len(all_rows)
    uploaded = 0
    for i in range(0, total, batch_size):
        batch = all_rows[i:i+batch_size]
        for attempt in range(3):  # 最大3回リトライ
            try:
                service.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id, range=f'{sheet_name}!A1',
                    valueInputOption='USER_ENTERED', body={'values': batch}
                ).execute()
                uploaded += len(batch)
                print(f"  [Batch] Uploaded rows {i+1}-{i+len(batch)} of {total} to '{sheet_name}'", flush=True)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"  [Batch] Retry {attempt+1}/3 for '{sheet_name}' (rows {i+1}-{i+len(batch)}): {e}", flush=True)
                    time.sleep(5)
                else:
                    print(f"  [Batch] FAILED after 3 attempts for '{sheet_name}' (rows {i+1}-{i+len(batch)}): {e}", flush=True)
        time.sleep(1)  # バッチ間に1秒待機
    print(f"  [Batch] Complete: {uploaded}/{total} rows uploaded to '{sheet_name}'.", flush=True)
    return uploaded

def main():
    service = get_sheets_service()
    
    SPREADSHEET_ID = "1ixdf0Ep4DWSYPPED0xwCqwuG0U-aRSyl_5JI801Jk4Q"
    print(f"--- Target Spreadsheet ID: {SPREADSHEET_ID} ---", flush=True)
    debug_print_sheet_names(service, SPREADSHEET_ID)
    
    # ヘッダーが無ければ自動挿入
    ensure_headers(service, SPREADSHEET_ID, 'raw_race_data', RAW_RACE_DATA_HEADERS)
    ensure_headers(service, SPREADSHEET_ID, 'history_results', HISTORY_RESULTS_HEADERS)
    ensure_headers(service, SPREADSHEET_ID, 'raw_beforeinfo', RAW_BEFOREINFO_HEADERS)

    # Job 1: Tomorrow's Program (22時実行なので翌日の出走表を取得)
    # 18時以降の実行は翌日の番組を取得、それ以前なら当日
    print(">>> STEP 1: Getting race program venues...", flush=True)
    
    # JST Timezone
    JST = timezone(timedelta(hours=9))
    now_jst = datetime.now(JST)
    
    if now_jst.hour >= 18:
        # 22時実行 → 翌日の番組を取得
        program_date = now_jst + timedelta(days=1)
        print(f">>> 18時以降の実行のため、翌日の番組を取得します", flush=True)
    else:
        program_date = now_jst
    
    program_date_str = program_date.strftime("%Y%m%d")
    print(f">>> Program date (JST): {program_date_str}", flush=True)
    
    try:
        venues_program = get_venues_for_date(program_date_str)
        print(f">>> Venues found: {venues_program}", flush=True)
    except Exception as e:
        print(f">>> ERROR getting venues: {e}", flush=True)
        venues_program = []
    
    if venues_program:
        print(f">>> Found {len(venues_program)} venues: {venues_program}", flush=True)
        print(f"Starting Program Scrape for {program_date_str}...", flush=True)
        program_rows = []
        for jcd in venues_program:
            print(f"  > Scraping Venue {jcd} Program...", end=" ", flush=True)
            venue_races = 0
            for rno in range(1, 13):
                time.sleep(0.3) 
                rows = scrape_program(jcd, rno, program_date_str)
                if rows:
                    program_rows.extend(rows)
                    venue_races += 1
            print(f"({venue_races} races found)")
        
        print(f">>> Total Program Rows collected: {len(program_rows)}", flush=True)
        if program_rows:
            batch_upload(service, SPREADSHEET_ID, 'raw_race_data', program_rows)
        else:
            print("WARNING: No program rows found for any venue.", flush=True)
    else:
        print(f"No race venues found for {program_date_str}.", flush=True)

    # Job 2: Results & BeforeInfo
    # 18時以降 → 当日の結果を取得（レース終了済み）
    # 18時以前 → 前日の結果を取得
    if now_jst.hour >= 18:
        result_date = now_jst
    else:
        result_date = now_jst - timedelta(days=1)
    result_date_str = result_date.strftime("%Y%m%d")
    print(f"\n>>> STEP 2: Getting results for {result_date_str}...", flush=True)
    venues_result = get_venues_for_date(result_date_str)
    
    if venues_result:
        print(f">>> Found {len(venues_result)} venues for {result_date_str}: {venues_result}", flush=True)
        result_rows = []
        beforeinfo_rows = []
        
        for jcd in venues_result:
            print(f"  > Scraping Venue {jcd} Results...", end=" ", flush=True)
            time.sleep(0.5) 
            rows = scrape_result_venue(jcd, result_date_str)
            if rows:
                result_rows.extend(rows)
                print(f"({len(rows)} rows)", end=" ")
            
            # 2. Before Info
            print(f"/ BeforeInfo (1-12R)...", end=" ")
            venue_before = 0
            for rno in range(1, 13):
                time.sleep(0.3)
                rows = scrape_beforeinfo(jcd, rno, result_date_str)
                if rows:
                    beforeinfo_rows.extend(rows)
                    venue_before += 1
            print(f"({venue_before} races)")

        # Upload Results
        print(f">>> Total Result Rows: {len(result_rows)}", flush=True)
        if result_rows:
            batch_upload(service, SPREADSHEET_ID, 'history_results', result_rows)
        
        # Upload BeforeInfo
        print(f">>> Total BeforeInfo Rows: {len(beforeinfo_rows)}", flush=True)
        if beforeinfo_rows:
            batch_upload(service, SPREADSHEET_ID, 'raw_beforeinfo', beforeinfo_rows)

    else:
        print(f"No race venues found for {result_date_str}.", flush=True)

if __name__ == "__main__":
    main()
