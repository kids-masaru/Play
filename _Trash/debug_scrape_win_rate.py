import requests
from bs4 import BeautifulSoup
import re

# 2026/02/07 徳山 1R (スクショにあるレース)
url = "https://www.boatrace.jp/owpc/pc/race/racelist?rno=1&jcd=18&hd=20260207"

print(f"Fetching URL: {url}")
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
response = requests.get(url, headers=headers)
response.encoding = response.apparent_encoding

soup = BeautifulSoup(response.text, 'html.parser')
tbodies = soup.find_all('tbody')

print(f"Found {len(tbodies)} tbodies (players). Checking first player...")

if tbodies:
    found_player_table = False
    for tbody in tbodies:
        # Check if this is a player table (has boat color)
        boat_td = tbody.find('td', class_=re.compile(r'is-boatColor\d'))
        if not boat_td:
            continue
            
        found_player_table = True
        print("-" * 40)
        print("Found Player Table!")
        
        # Check Player Name
        name_div = tbody.find('div', class_=lambda x: x and 'is-fs18' in x and 'is-fBold' in x)
        name = name_div.text.strip().replace("\u3000", "") if name_div else "Unknown"
        print(f"Player Name: {name}")

        # Inspect all TDs
        tds = tbody.find_all('td')
        print(f"Found {len(tds)} TDs. Checking content:")
        
        for i, td in enumerate(tds):
            text = td.get_text(strip=True)
            print(f"  TD[{i}]: '{text}'")
            
            # Test Regex
            # win_rate regex: ^[1-9]\.\d{2}$
            rate_match = re.match(r'^[1-9]\.\d{2}$', text)
            if rate_match:
                print(f"    -> MATCHED Win Rate Pattern!")
            
        # Only check the first player matching the criteria to avoid spam
        break
    
    if not found_player_table:
        print("No player table found with is-boatColor class.")
