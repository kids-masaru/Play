"""
evaluator.py - 自己改善ループの評価指標計算モジュール

入力: 買い目DataFrame（race_id, combo, stake） + 実結果 + オッズ
出力: ROI / 的中率 / 取引回数 / 複合スコア

設計メモ:
- ROI計算ロジックは generate_dashboard_data.py と整合
- 複合スコアの定義は auto_research/spec.md に準拠
"""
import pandas as pd
import numpy as np

# --- 設定 ---
MIN_TRADES = 30          # 取引回数の下限（検証30日で30件）
HIT_RATE_DEAD_LINE = 5.0 # 的中率(%)がこれ未満なら強制失格


def evaluate(buy_df: pd.DataFrame, results_df: pd.DataFrame, odds_df: pd.DataFrame) -> dict:
    """買い目・実結果・オッズから指標を計算する。

    Args:
        buy_df: 買い目DataFrame。必須カラム: race_id(str), combo(str, "1-2-3"形式), stake(int, 円)
        results_df: 実結果DataFrame。必須カラム: ID(str), Result(str, "1-2-3"), Payout(数値)
        odds_df: オッズDataFrame。必須カラム: ID(str), Combination(str), Odds(float)
                  ※未使用（払戻金から実オッズを逆算できるため）だが、将来の拡張用に受け取る。

    Returns:
        dict: roi, hit_rate, n_trades, n_hits, invest, return, composite_score
    """
    if buy_df.empty:
        return _empty_metrics("buy_dfが空")

    # ID→Result, Payout の辞書化
    results_df = results_df.drop_duplicates(subset=["ID"], keep="last")
    res_dict = {}
    for _, row in results_df.iterrows():
        rid = str(row["ID"])
        try:
            payout = int(float(row["Payout"]))
        except (ValueError, TypeError):
            payout = 0
        result_combo = str(row["Result"]).replace("-", "")
        res_dict[rid] = (result_combo, payout)

    total_invest = 0
    total_return = 0
    n_trades = 0
    n_hits = 0

    for _, row in buy_df.iterrows():
        rid = str(row["race_id"])
        combo = str(row["combo"]).replace("-", "")
        stake = int(row["stake"])

        if rid not in res_dict:
            continue  # 結果が無いレースはスキップ

        result_combo, payout = res_dict[rid]
        total_invest += stake
        n_trades += 1

        if combo == result_combo:
            # 的中: payoutは100円ベットあたりの払戻額
            total_return += (stake // 100) * payout
            n_hits += 1

    if total_invest == 0:
        return _empty_metrics("投資額0")

    roi = round(total_return / total_invest * 100, 2)
    hit_rate = round(n_hits / n_trades * 100, 2) if n_trades > 0 else 0.0
    composite_score = _composite(roi, hit_rate, n_trades)

    return {
        "roi": roi,
        "hit_rate": hit_rate,
        "n_trades": n_trades,
        "n_hits": n_hits,
        "invest": total_invest,
        "return": total_return,
        "composite_score": composite_score,
    }


def _composite(roi: float, hit_rate: float, n_trades: int) -> float:
    """複合スコアを計算する。

    composite_score =
        roi
        - max(0, MIN_TRADES - n_trades) * 2       (取引少ペナルティ)
        - (99999 if hit_rate < HIT_RATE_DEAD_LINE else 0)  (論外失格)
    """
    score = roi
    if n_trades < MIN_TRADES:
        score -= (MIN_TRADES - n_trades) * 2
    if hit_rate < HIT_RATE_DEAD_LINE:
        score -= 99999
    return round(score, 2)


def _empty_metrics(reason: str) -> dict:
    return {
        "roi": 0.0,
        "hit_rate": 0.0,
        "n_trades": 0,
        "n_hits": 0,
        "invest": 0,
        "return": 0,
        "composite_score": -99999.0,
        "note": reason,
    }


# --- サニティチェック用 ---
if __name__ == "__main__":
    # 最小ケース: 3レース、1レースだけ的中
    buy = pd.DataFrame([
        {"race_id": "R1", "combo": "1-2-3", "stake": 100},
        {"race_id": "R2", "combo": "2-3-1", "stake": 100},
        {"race_id": "R3", "combo": "4-5-6", "stake": 100},
    ])
    res = pd.DataFrame([
        {"ID": "R1", "Result": "1-2-3", "Payout": 1500},  # 的中
        {"ID": "R2", "Result": "3-1-2", "Payout": 1200},  # 外れ
        {"ID": "R3", "Result": "1-2-3", "Payout": 800},   # 外れ
    ])
    odds = pd.DataFrame()  # 未使用

    m = evaluate(buy, res, odds)
    print("サニティ結果:", m)
    assert m["n_trades"] == 3
    assert m["n_hits"] == 1
    assert m["invest"] == 300
    assert m["return"] == 1500
    # ROI = return/invest*100 = 1500/300*100 = 500.0 (回収率)
    assert m["roi"] == 500.0
    print("テスト通過")
