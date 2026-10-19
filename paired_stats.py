"""同じレースどうしの損益差を比べる、共通の統計（ペア・ブートストラップと判定）。

まとめページ（build_overview.py）と Jev 組合せ成績（jev_pairing_performance.py）で
同じ計算・同じ判定基準を使うために切り出した（spec「評価」：指標計算の共通化）。
"""

from __future__ import annotations

import random
from typing import Any

DECISION_SAMPLE = 500  # 正式判断の目安（1モデルあたりの件数）。これ未満は優劣を断定しない
MIN_CI_SAMPLE = 30  # これ未満は区間も出さない
BOOTSTRAP_ROUNDS = 2000
BOOTSTRAP_SEED = 20261015


def paired_bootstrap(
    diffs: list[float], rounds: int = BOOTSTRAP_ROUNDS, seed: int = BOOTSTRAP_SEED
) -> dict[str, Any]:
    """同じレースの損益差（あり−なし）の平均と95%区間（ペア・ブートストラップ）。"""
    n = len(diffs)
    if n < MIN_CI_SAMPLE:
        return {"n": n, "mean_diff_yen": round(sum(diffs) / n, 1) if n else None, "ci95": None}
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(rounds))
    low = means[int(rounds * 0.025)]
    high = means[int(rounds * 0.975) - 1]
    return {"n": n, "mean_diff_yen": round(sum(diffs) / n, 1), "ci95": [round(low, 1), round(high, 1)]}


def verdict(diff: dict[str, Any]) -> str:
    """判定：蓄積中／ありが優勢／なしが優勢／差なし（500件までは蓄積中）。"""
    if diff["n"] < DECISION_SAMPLE or not diff.get("ci95"):
        return "accruing"
    low, high = diff["ci95"]
    if low > 0:
        return "playbook_better"
    if high < 0:
        return "baseline_better"
    return "no_difference"
