import os
import pandas as pd
import json
import re
from datetime import datetime, timedelta
import database as db

# --- Settings ---
DATA_DIR = "daily_data"
PRED_FILE = os.path.join(DATA_DIR, "daily_predictions.csv")
RES_FILE = os.path.join(DATA_DIR, "daily_history_results.csv")
ODDS_FILE = os.path.join(DATA_DIR, "daily_odds_3t.csv")
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

def load_odds_dict():
    """オッズCSVからレースID+組み合わせ → オッズ値の辞書を作成する"""
    if not os.path.exists(ODDS_FILE):
        return {}
    try:
        df_odds = pd.read_csv(ODDS_FILE)
        odds_dict = {}
        for _, row in df_odds.iterrows():
            key = f"{row['ID']}_{str(row['Combination']).replace('-', '')}"
            odds_dict[key] = float(row['Odds'])
        return odds_dict
    except Exception:
        return {}


def parse_reasoning(pred_text):
    """AIの予測テキストから展開予想と推奨理由を抽出する"""
    try:
        text = str(pred_text)
        # 「■展開予想と推奨理由」の後ろ〜「■最終推奨買い目」の前を抽出
        if '■展開予想と推奨理由' in text:
            reasoning = text.split('■展開予想と推奨理由')[1]
            if '■最終推奨買い目' in reasoning:
                reasoning = reasoning.split('■最終推奨買い目')[0]
            return reasoning.strip()[:300]
        # フォールバック: 買い目の前の部分を取る
        if '■最終推奨買い目' in text:
            return text.split('■最終推奨買い目')[0].strip()[-300:]
        return text[:200]
    except:
        return ""

def calculate_roi():
    if not os.path.exists(PRED_FILE) or not os.path.exists(RES_FILE):
        return

    df_p = pd.read_csv(PRED_FILE)
    df_r = pd.read_csv(RES_FILE)
    df_r = df_r.drop_duplicates(subset=['ID'], keep='last')
    res_dict = df_r.set_index('ID')[['Result', 'Payout']].to_dict('index')

    # オッズデータを読み込み
    odds_dict = load_odds_dict()

    results = []
    for _, row in df_p.iterrows():
        rid = str(row['RaceID'])
        if rid in res_dict:
            res_val = str(res_dict[rid]['Result']).replace('-', '')
            try:
                payout = int(float(res_dict[rid]['Payout']))
            except (ValueError, TypeError):
                payout = 0
            eyes = parse_buy_str(str(row['Prediction']))
            if not eyes: continue

            is_hit = res_val in eyes

            # Stakesカラムがあればケリー額を使用、なければ固定3000円にフォールバック
            stakes_dict = {}
            raw_stakes = row.get('Stakes', '') if 'Stakes' in row.index else ''
            if raw_stakes and str(raw_stakes).strip() not in ('', 'nan'):
                try:
                    stakes_dict = json.loads(str(raw_stakes))
                except Exception:
                    stakes_dict = {}

            if stakes_dict:
                invest = sum(stakes_dict.values())
                ret = (stakes_dict.get(res_val, 0) // 100) * payout if is_hit else 0
            else:
                num_tickets = len(eyes)
                stake_per_eye = (3000 // num_tickets // 100) * 100
                if stake_per_eye == 0:
                    stake_per_eye = 100
                invest = stake_per_eye * num_tickets
                ret = payout * (stake_per_eye // 100) if is_hit else 0

            # 各買い目の事前オッズを取得（あれば）
            pre_odds_list = []
            for eye in eyes:
                key = f"{rid}_{eye}"
                if key in odds_dict:
                    pre_odds_list.append(odds_dict[key])
            avg_pre_odds = round(sum(pre_odds_list) / len(pre_odds_list), 1) if pre_odds_list else None

            # 的中した買い目の事前オッズ
            hit_pre_odds = None
            if is_hit:
                hit_key = f"{rid}_{res_val}"
                if hit_key in odds_dict:
                    hit_pre_odds = odds_dict[hit_key]

            reasoning = parse_reasoning(row['Prediction'])

            results.append({
                "id": rid,
                "date": row['Date'],
                "invest": invest,
                "return": ret,
                "is_hit": is_hit,
                "venue": row['Venue'],
                "r": row['R'],
                "result_eye": res_val,
                "odds": round(payout / 100, 1) if payout > 0 else 0,
                "pre_odds": hit_pre_odds if hit_pre_odds else avg_pre_odds,
                "ev_category": "高EV" if avg_pre_odds and avg_pre_odds > 30 else
                               "中EV" if avg_pre_odds and avg_pre_odds > 10 else
                               "低EV" if avg_pre_odds else None,
                "ai_reasoning": reasoning
            })

    df_res = pd.DataFrame(results)
    if df_res.empty: return
    df_res['date'] = pd.to_datetime(df_res['date'])
    
    # 期間ごとの集計
    now = df_res['date'].max()
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    # 場所別集計
    venue_grouped = df_res.groupby('venue').agg(
        invest=('invest', 'sum'),
        return_val=('return', 'sum'),
        hit_rate=('is_hit', 'mean'),
        races=('id', 'count')
    ).reset_index()
    venue_grouped['roi'] = venue_grouped.apply(lambda x: round(x['return_val'] / x['invest'] * 100, 1) if x['invest'] > 0 else 0, axis=1)
    venue_grouped['hit_rate'] = (venue_grouped['hit_rate'] * 100).round(1)
    venue_grouped = venue_grouped.rename(columns={'return_val': 'return'})
    venue_stats = venue_grouped.to_dict('records')

    # レース番号別集計
    r_grouped = df_res.groupby('r').agg(
        invest=('invest', 'sum'),
        return_val=('return', 'sum'),
        hit_rate=('is_hit', 'mean'),
        races=('id', 'count')
    ).reset_index()
    r_grouped['roi'] = r_grouped.apply(lambda x: round(x['return_val'] / x['invest'] * 100, 1) if x['invest'] > 0 else 0, axis=1)
    r_grouped['hit_rate'] = (r_grouped['hit_rate'] * 100).round(1)
    r_grouped = r_grouped.rename(columns={'return_val': 'return'})
    race_stats = r_grouped.to_dict('records')

    # EV分布集計
    ev_grouped = df_res.groupby(df_res['ev_category'].fillna('未知')).agg(
        invest=('invest', 'sum'),
        return_val=('return', 'sum'),
        hit_rate=('is_hit', 'mean'),
        races=('id', 'count')
    ).reset_index()
    ev_grouped['roi'] = ev_grouped.apply(lambda x: round(x['return_val'] / x['invest'] * 100, 1) if x['invest'] > 0 else 0, axis=1)
    ev_grouped['hit_rate'] = (ev_grouped['hit_rate'] * 100).round(1)
    ev_grouped = ev_grouped.rename(columns={'ev_category': 'category', 'return_val': 'return'})
    ev_stats = ev_grouped.to_dict('records')

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
        "recent_races": results[-20:][::-1],
        "venue_stats": venue_stats,
        "race_stats": race_stats,
        "ev_stats": ev_stats
    }

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    calculate_roi()
