"""統計モデルによる 1X2(ホーム勝/引分/アウェイ勝) 予測。

手法: 簡易ポアソンモデル（Dixon-Coles 系の軽量版）
  - 各チームの「攻撃力 attack」「守備力 defense」を直近N試合から算出
    attack  = そのチームの1試合平均得点 / リーグ平均
    defense = そのチームの1試合平均失点 / リーグ平均
  - 予測の期待得点:
    λ_home = リーグ平均得点 × attack[home] × defense[away] × ホーム補正
    λ_away = リーグ平均得点 × attack[away] × defense[home] / ホーム補正
  - 両者をポアソン分布として全スコアの確率を合計 → P(H), P(D), P(A)
  - リーク防止: 各試合の予測には「その試合より前」の試合だけを使う

CLI:
  python toto/predict_stats.py --backtest        # 2025年で的中率を検証
"""
import os
import sys
import io
import bisect
from math import exp, factorial
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")  # 冪等。import 経由でも stdout を壊さない
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
MATCHES_CSV = os.path.join(ROOT, "data", "jleague_matches.csv")

LOOKBACK = 30      # 直近何試合で強さを測るか
MIN_GAMES = 5      # これ未満は平均的チーム(attack=defense=1)扱い
HOME_BOOST = 1.10  # ホーム補正(経験的)
MAX_GOALS = 8      # ポアソン合計の打ち切り


def poisson_pmf(k, lam):
    return exp(-lam) * lam ** k / factorial(k)


def match_probs(lam_h, lam_a, maxg=MAX_GOALS):
    """期待得点(λ)から P(H), P(D), P(A) を返す。"""
    ph = [poisson_pmf(i, lam_h) for i in range(maxg + 1)]
    pa = [poisson_pmf(j, lam_a) for j in range(maxg + 1)]
    pH = pD = pA = 0.0
    for i in range(maxg + 1):
        for j in range(maxg + 1):
            p = ph[i] * pa[j]
            if i > j:
                pH += p
            elif i == j:
                pD += p
            else:
                pA += p
    s = pH + pD + pA
    return pH / s, pD / s, pA / s


class StatsModel:
    """直近フォームからチーム強度を測り、1X2確率を出すモデル。"""

    def __init__(self, lookback=LOOKBACK, min_games=MIN_GAMES, home_boost=HOME_BOOST):
        self.lookback = lookback
        self.min_games = min_games
        self.home_boost = home_boost
        # team -> ソート済み [(date, gf, ga), ...]
        self._hist = {}
        # 全試合の平均得点(1チーム1試合あたり)
        self._league_avg = 1.3

    def fit(self, df):
        """履歴をチームごとに時系列で蓄積。df は結果確定済みのみ使用。"""
        d = df[df["result"].isin(["H", "D", "A"])].copy()
        d = d.sort_values(["date", "kickoff"], na_position="last")
        goals = []
        for _, r in d.iterrows():
            hg, ag = r["home_goals"], r["away_goals"]
            self._hist.setdefault(r["home"], []).append((r["date"], hg, ag))
            self._hist.setdefault(r["away"], []).append((r["date"], ag, hg))
            goals.append(hg)
            goals.append(ag)
        self._league_avg = (sum(goals) / len(goals)) if goals else 1.3
        # 各チームの日付列(二分探索用)
        self._dates = {t: [x[0] for x in v] for t, v in self._hist.items()}
        return self

    def _strength(self, team, before_date):
        """before_date より前の直近N試合から (attack, defense) を返す。"""
        hist = self._hist.get(team)
        if not hist:
            return 1.0, 1.0
        idx = bisect.bisect_left(self._dates[team], before_date)
        window = hist[max(0, idx - self.lookback):idx]
        if len(window) < self.min_games:
            return 1.0, 1.0
        gf = sum(w[1] for w in window) / len(window)
        ga = sum(w[2] for w in window) / len(window)
        attack = gf / self._league_avg if self._league_avg else 1.0
        defense = ga / self._league_avg if self._league_avg else 1.0
        return attack, defense

    def predict(self, home, away, date):
        """1試合の (P_H, P_D, P_A) と予想(H/D/A)を返す。"""
        a_h, d_h = self._strength(home, date)
        a_a, d_a = self._strength(away, date)
        lam_h = self._league_avg * a_h * d_a * self.home_boost
        lam_a = self._league_avg * a_a * d_h / self.home_boost
        pH, pD, pA = match_probs(lam_h, lam_a)
        pick = max((("H", pH), ("D", pD), ("A", pA)), key=lambda x: x[1])[0]
        return {"p_H": pH, "p_D": pD, "p_A": pA, "pick": pick,
                "lam_h": lam_h, "lam_a": lam_a}


def backtest(test_year=2025):
    """test_year を予測対象に、それ以前+当年の前節までで予測して的中率を測る。"""
    df = pd.read_csv(MATCHES_CSV, dtype={"date": str})
    df = df[df["result"].isin(["H", "D", "A"])].copy()

    model = StatsModel().fit(df)  # 履歴は全期間（各予測は date 以前のみ参照=リークなし）

    test = df[df["season"].astype(str) == str(test_year)].copy()
    test = test.sort_values(["date", "kickoff"])

    n = hit = 0
    logloss = 0.0
    base_hit = 0  # ベースライン: 常にホーム(H)
    import math
    for _, r in test.iterrows():
        pr = model.predict(r["home"], r["away"], r["date"])
        actual = r["result"]
        n += 1
        if pr["pick"] == actual:
            hit += 1
        if actual == "H":
            base_hit += 1
        p_actual = {"H": pr["p_H"], "D": pr["p_D"], "A": pr["p_A"]}[actual]
        logloss += -math.log(max(p_actual, 1e-9))

    print(f"=== バックテスト {test_year} ===")
    print(f"対象試合: {n}")
    print(f"統計モデル 的中率: {hit/n*100:.1f}%  ({hit}/{n})")
    print(f"ベースライン(常にホーム) 的中率: {base_hit/n*100:.1f}%")
    print(f"平均 log loss: {logloss/n:.3f}  (低いほど良い / 3択ランダム=1.099)")


if __name__ == "__main__":
    if "--backtest" in sys.argv:
        backtest()
    else:
        print("使い方: python toto/predict_stats.py --backtest")
