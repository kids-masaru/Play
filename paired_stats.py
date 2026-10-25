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


def _number(value: Any) -> float:
    """集計用の値を数値化し、不正値は安全側の0として扱う。"""

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def robustness_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """実収支と、高配当への依存を確認する共通のストレス指標を返す。

    「最大／上位3的中除外」は的中を無効にする評価ではない。該当レースの
    投資と払戻を両方外し、残りの購入だけでROIを再計算する仮想テストである。
    入力順を時系列として最大ドローダウンと連敗数を計算する。
    """

    normalized = [
        {
            "invest": _number(row.get("invest")),
            "return": _number(row.get("return")),
        }
        for row in rows
    ]
    purchased = [row for row in normalized if row["invest"] > 0]
    invest = sum(row["invest"] for row in purchased)
    returned = sum(row["return"] for row in purchased)
    hits = sum(row["return"] > 0 for row in purchased)

    equity = peak = max_drawdown = 0.0
    losing_streak = longest_losing_streak = 0
    for row in purchased:
        equity += row["return"] - row["invest"]
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if row["return"] > 0:
            losing_streak = 0
        else:
            losing_streak += 1
            longest_losing_streak = max(longest_losing_streak, losing_streak)

    win_indexes = sorted(
        (index for index, row in enumerate(purchased) if row["return"] > 0),
        key=lambda index: purchased[index]["return"],
        reverse=True,
    )

    def stress_without(count: int) -> tuple[float | None, float | None]:
        """払戻上位countレースを丸ごと外したROIと収支を返す。"""

        excluded = set(win_indexes[:count])
        remaining = [row for index, row in enumerate(purchased) if index not in excluded]
        rest_invest = sum(row["invest"] for row in remaining)
        rest_return = sum(row["return"] for row in remaining)
        if not excluded or rest_invest <= 0:
            return None, None
        return rest_return / rest_invest * 100, rest_return - rest_invest

    roi_without_largest, profit_without_largest = stress_without(1)
    roi_without_top3, profit_without_top3 = stress_without(3)
    largest_return = purchased[win_indexes[0]]["return"] if win_indexes else 0.0
    top3_return = sum(purchased[index]["return"] for index in win_indexes[:3])
    largest_profit = max(
        (row["return"] - row["invest"] for row in purchased),
        default=0.0,
    )

    return {
        "graded_races": len(normalized),
        "purchased_races": len(purchased),
        "hits": hits,
        "hit_rate_pct": round(hits / len(purchased) * 100, 1) if purchased else None,
        "invest_yen": round(invest),
        "return_yen": round(returned),
        "profit_yen": round(returned - invest),
        "roi_pct": round(returned / invest * 100, 1) if invest else None,
        "max_drawdown_yen": round(max_drawdown),
        "longest_losing_streak": longest_losing_streak if purchased else None,
        "largest_single_race_return_yen": round(largest_return),
        "largest_single_race_profit_yen": round(max(0.0, largest_profit)),
        "largest_return_share_pct": round(largest_return / returned * 100, 1) if returned > 0 else None,
        "top3_return_share_pct": round(top3_return / returned * 100, 1) if returned > 0 else None,
        "profit_without_largest_win_yen": round(profit_without_largest) if profit_without_largest is not None else None,
        "roi_without_largest_win_pct": round(roi_without_largest, 1) if roi_without_largest is not None else None,
        "profit_without_top3_wins_yen": round(profit_without_top3) if profit_without_top3 is not None else None,
        "roi_without_top3_wins_pct": round(roi_without_top3, 1) if roi_without_top3 is not None else None,
    }


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
