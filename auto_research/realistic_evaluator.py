"""
realistic_evaluator.py - 本番(morning_odds_runner.py)準拠の買い目生成 + 評価

現行 evaluator.py との違い:
- LightGBM確率の top3 を全レース100円で買う ❌
- 実オッズと EV を計算し、EV > 1.0 で絞り込み、Kelly基準で stake を変動 ✅
- 1日あたり最大10レース、1レースあたり最大4買い目 (LLMフィルタの決定論的代替)

これにより auto_research のスコアが現実の運用ROIと噛み合うようになる。
"""
import pandas as pd
import numpy as np

# --- 本番準拠の定数 ---
# (morning_odds_runner.py: EV_THRESHOLD=1.0, top10レース)
# (local_ai_pipeline.py: kelly_stake bankroll=10000, fraction=0.5, min=100, max=5000)
EV_THRESHOLD = 1.0
TOP_N_RACES_PER_DAY = 10
TOP_N_COMBOS_PER_RACE = 4   # 本番LLMが3〜5個選ぶ実態の決定論的近似

KELLY_BANKROLL = 10000
KELLY_FRACTION = 0.5
KELLY_MIN = 100
KELLY_MAX = 5000


def kelly_stake(prob: float, odds: float) -> int:
    """ハーフケリー基準で stake 額(100円単位)を返す。EV<=1.0 なら 0。"""
    if odds <= 1.0 or prob <= 0:
        return 0
    f = (prob * odds - 1.0) / (odds - 1.0)
    if f <= 0:
        return 0
    s = int(KELLY_BANKROLL * f * KELLY_FRACTION // 100) * 100
    return max(KELLY_MIN, min(KELLY_MAX, s))


def estimate_trifecta_probs_full(p1, p2, p3):
    """3モデル確率から全120通りの3連単確率を推定して正規化"""
    combos = []
    for i in range(6):
        pi = p1[i]
        if pi < 0.01:
            continue
        denom2 = max(1.0 - p2[i], 1e-10)
        for j in range(6):
            if j == i:
                continue
            pj = p2[j] / denom2
            denom3 = max(1.0 - p3[i] - p3[j], 1e-10)
            for k in range(6):
                if k == i or k == j:
                    continue
                pk = p3[k] / denom3
                combos.append((f"{i+1}-{j+1}-{k+1}", pi * pj * pk))
    combos.sort(key=lambda x: x[1], reverse=True)
    total = sum(p for _, p in combos)
    if total > 0:
        combos = [(c, p / total) for c, p in combos]
    return combos


def simulate_realistic_buys(val_df: pd.DataFrame,
                            feature_cols: list,
                            m1, m2, m3,
                            odds_df: pd.DataFrame,
                            odds_max: float = None,
                            prob_min: float = None,
                            ev_threshold: float = None) -> pd.DataFrame:
    """本番準拠ロジックで val 期間の買い目DFを返す。

    Args:
        odds_max: 指定すれば odds がこれ以下の combo のみ買う（moonshot除外）
        prob_min: 指定すれば prob がこれ以上の combo のみ買う（低確率除外）
        ev_threshold: EV 下限。Noneなら EV_THRESHOLD (1.0) を使う

    戻り値の列: race_id, combo, stake, ev, odds_pre, prob, date
    """
    ev_thr = EV_THRESHOLD if ev_threshold is None else ev_threshold
    val_df = val_df.reset_index(drop=True).copy()
    X = val_df[feature_cols]
    probs_1 = m1.predict(X)
    probs_2 = m2.predict(X)
    probs_3 = m3.predict(X)

    # オッズを race_id ごとに辞書化
    odds_by_race = {}
    for rid, grp in odds_df.groupby('ID'):
        d = {}
        for _, r in grp.iterrows():
            try:
                d[str(r['Combination'])] = float(r['Odds'])
            except (ValueError, TypeError):
                continue
        odds_by_race[str(rid)] = d

    buys = []
    # 日別グループで「その日の最大EVトップNレース」を選ぶ (本番と同じ)
    val_df['__idx'] = val_df.index
    for date, day_grp in val_df.groupby('Date'):
        race_ev_pool = []
        for _, row in day_grp.iterrows():
            idx = row['__idx']
            rid = str(row['ID'])
            if rid not in odds_by_race:
                continue
            combos = estimate_trifecta_probs_full(probs_1[idx], probs_2[idx], probs_3[idx])
            race_odds = odds_by_race[rid]
            ev_combos = []
            for combo, prob in combos:
                if combo in race_odds:
                    odds = race_odds[combo]
                    ev = prob * odds
                    if ev <= ev_thr:
                        continue
                    if odds_max is not None and odds > odds_max:
                        continue
                    if prob_min is not None and prob < prob_min:
                        continue
                    ev_combos.append((combo, ev, odds, prob))
            if ev_combos:
                ev_combos.sort(key=lambda x: x[1], reverse=True)
                max_ev = ev_combos[0][1]
                race_ev_pool.append((rid, max_ev, ev_combos, date))

        # その日の max_ev で top N レース
        race_ev_pool.sort(key=lambda x: x[1], reverse=True)
        for rid, _, ev_combos, dval in race_ev_pool[:TOP_N_RACES_PER_DAY]:
            for combo, ev, odds, prob in ev_combos[:TOP_N_COMBOS_PER_RACE]:
                stake = kelly_stake(prob, odds)
                if stake > 0:
                    buys.append({
                        'race_id': rid,
                        'combo': combo.replace('-', ''),
                        'stake': stake,
                        'ev': round(ev, 3),
                        'odds_pre': round(odds, 2),
                        'prob': round(prob, 5),
                        'date': str(dval)[:10],
                    })

    return pd.DataFrame(buys)


def evaluate_buys(buy_df: pd.DataFrame, results_df: pd.DataFrame) -> dict:
    """買い目DF と結果DF から ROI/的中率を計算"""
    if buy_df.empty:
        return {'roi': 0.0, 'hit_rate': 0.0, 'n_trades': 0, 'n_hits': 0,
                'invest': 0, 'return': 0, 'n_races': 0}

    res_dict = {}
    for _, r in results_df.drop_duplicates(subset=['ID'], keep='last').iterrows():
        rid = str(r['ID'])
        try:
            payout = int(float(r['Payout']))
        except (ValueError, TypeError):
            payout = 0
        result_combo = str(r['Result']).replace('-', '')
        res_dict[rid] = (result_combo, payout)

    total_invest = 0
    total_return = 0
    n_trades = 0
    n_hits = 0
    races_bet = set()

    for _, row in buy_df.iterrows():
        rid = str(row['race_id'])
        combo = str(row['combo']).replace('-', '')
        stake = int(row['stake'])
        if rid not in res_dict:
            continue
        result_combo, payout = res_dict[rid]
        total_invest += stake
        n_trades += 1
        races_bet.add(rid)
        if combo == result_combo:
            total_return += (stake // 100) * payout
            n_hits += 1

    if total_invest == 0:
        return {'roi': 0.0, 'hit_rate': 0.0, 'n_trades': 0, 'n_hits': 0,
                'invest': 0, 'return': 0, 'n_races': 0}

    roi = round(total_return / total_invest * 100, 2)
    hit_rate = round(n_hits / n_trades * 100, 2)
    return {
        'roi': roi,
        'hit_rate': hit_rate,
        'n_trades': n_trades,
        'n_hits': n_hits,
        'invest': total_invest,
        'return': total_return,
        'n_races': len(races_bet),
    }
