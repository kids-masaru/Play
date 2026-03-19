import os
import pandas as pd
import json
import re
from datetime import datetime, timedelta

# --- Settings ---
DATA_DIR = "daily_data"
PRED_FILE = os.path.join(DATA_DIR, "daily_predictions.csv")
RES_FILE = os.path.join(DATA_DIR, "daily_history_results.csv")
# GitHub Pagesデプロイ用に、dashboardのpublicフォルダにも保存するようにする
OUTPUT_JSON = os.path.join("dashboard", "public", "daily_data", "dashboard_data.json")

def parse_buy_str(pred_text):
    """AIの予測テキストから買い目を抽出する"""
    try:
        buy_part = pred_text.split('■最終推奨買い目')[1].strip()
        eyes = re.findall(r'\d-\d-\d|\d{3}', buy_part)
        return [e.replace('-', '') for e in eyes]
    except:
        return []

def get_stats(df):
    if df.empty:
        return {"invest": 0, "return": 0, "roi": 0, "hit_rate": 0}
    invest = int(df['invest'].sum())
    ret = int(df['return'].sum())
    roi = round(ret / invest * 100, 1) if invest > 0 else 0
    hit_rate = round(df['is_hit'].mean() * 100, 1)
    return {"invest": invest, "return": ret, "roi": roi, "hit_rate": hit_rate}

def calculate_roi():
    if not os.path.exists(PRED_FILE) or not os.path.exists(RES_FILE):
        return

    df_p = pd.read_csv(PRED_FILE)
    df_r = pd.read_csv(RES_FILE)
    df_r = df_r.drop_duplicates(subset=['ID'], keep='last')
    res_dict = df_r.set_index('ID')[['Result', 'Payout']].to_dict('index')

    results = []
    for _, row in df_p.iterrows():
        rid = str(row['RaceID'])
        if rid in res_dict:
            res_val = str(res_dict[rid]['Result']).replace('-', '')
            payout = int(res_dict[rid]['Payout'])
            eyes = parse_buy_str(str(row['Prediction']))
            if not eyes: continue
            
            num_tickets = len(eyes)
            stake_per_eye = (3000 // num_tickets // 100) * 100
            invest = stake_per_eye * num_tickets
            is_hit = res_val in eyes
            ret = payout * (stake_per_eye // 100) if is_hit else 0
            
            results.append({
                "id": rid,
                "date": row['Date'],
                "invest": invest,
                "return": ret,
                "is_hit": is_hit,
                "venue": row['Venue'],
                "r": row['R'],
                "result_eye": res_val,
                "odds": round(payout / 100, 1)
            })

    df_res = pd.DataFrame(results)
    if df_res.empty: return
    df_res['date'] = pd.to_datetime(df_res['date'])
    
    # 期間ごとの集計
    now = df_res['date'].max()
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    summary = {
        "total": get_stats(df_res),
        "monthly": get_stats(df_res[df_res['date'] > last_30d]),
        "weekly": get_stats(df_res[df_res['date'] > last_7d]),
        "daily_history": df_res.groupby(df_res['date'].dt.date).agg({
            'invest': 'sum', 'return': 'sum'
        }).reset_index().assign(
            roi=lambda x: (x['return']/x['invest']*100).round(1),
            date=lambda x: x['date'].apply(lambda d: d.strftime('%Y-%m-%d'))
        ).to_dict('records'),
        "recent_races": results[-20:][::-1]
    }

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    calculate_roi()
