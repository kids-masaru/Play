import pandas as pd
import random
from datetime import datetime, timedelta

# File path
file_path = "c:/Users/HP/OneDrive/ドキュメント/Play/boat_race_analysis.xlsx"

# Settings
num_days = 90
races_per_day = 12
venues = ["桐生", "戸田", "江戸川", "平和島", "多摩川"]
players = [
    {"id": "4320", "name": "峰竜太"},
    {"id": "3897", "name": "白井英治"},
    {"id": "4418", "name": "茅原悠紀"},
    {"id": "4238", "name": "毒島誠"},
    {"id": "4831", "name": "羽野直也"},
    {"id": "4024", "name": "井口佳典"},
    {"id": "4444", "name": "桐生順平"},
    {"id": "3941", "name": "池田浩二"},
    {"id": "4500", "name": "山田康二"},
    {"id": "4168", "name": "石野貴之"}
]

data = []
start_date = datetime.now() - timedelta(days=num_days)

print("Generating mock data...")

for day in range(num_days):
    current_date = start_date + timedelta(days=day)
    date_str = current_date.strftime("%Y-%m-%d")
    
    # Randomly select 2 venues per day
    daily_venues = random.sample(venues, 2)
    
    for venue in daily_venues:
        for race_no in range(1, races_per_day + 1):
            race_id = f"{date_str}_{venue}_{race_no}"
            
            # Select 6 players for the race
            race_players = random.sample(players, 6)
            
            # Mock results (shuffle rank 1-6)
            ranks = list(range(1, 7))
            random.shuffle(ranks)
            
            for lane in range(1, 7):
                player = race_players[lane - 1]
                rank = ranks[lane - 1]
                
                # Mock ST (Start Timing) - slightly random but around 0.15
                st = round(random.uniform(0.05, 0.25), 2)
                
                # Mock Engine No
                engine_no = random.randint(10, 70)
                
                # Append row
                data.append({
                    "race_date": current_date, # Date object for Excel date format
                    "venue": venue,
                    "race_no": race_no,
                    "race_id": race_id,
                    "lane": lane,
                    "player_id": player["id"],
                    "player_name": player["name"],
                    "engine_no": engine_no,
                    "rank": rank,
                    "st": st,
                    "entry_count": 6
                })

# Create DataFrame
df_mock = pd.DataFrame(data)

# Load existing workbook to preserve other sheets/formulas
# Note: appending to existing sheet in openpyxl with pandas is tricky, 
# easiest is to use openpyxl directly or overwrite the specific sheet.
# Since we just recreated it empty, we can just replace 'raw_results'

with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
    df_mock.to_excel(writer, sheet_name='raw_results', index=False)

print(f"Successfully injected {len(df_mock)} rows of mock data into {file_path}")
