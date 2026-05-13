"""
experiment_wf.py - 自己改善ループの1試行実行スクリプト (walk-forward版)

処理の流れ:
1. build_features.py を呼んで ml_features.csv を再生成
2. 短縮版WFでスコア計算
   (a) 直近6ヶ月のモデル精度評価 (Brier/log-loss/top-3 acc)
   (b) 45日 実オッズROI評価 (Det モード)
3. wf_baseline.json と比較して採用判定
4. results.tsv に1行追記 (採用/不採用フラグ込み)

使用法:
    python auto_research/experiment_wf.py --note "変更内容の短い説明"

採用条件 (AND):
    主条件: 6ヶ月WF accuracy で Brier_1st が改善 (低下) + top3_acc 改善
    副条件: 45日WF Det ROI がベースラインから -10pt 以内
"""
import os
import sys
import json
import argparse
import subprocess
import importlib
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auto_research import walkforward_evaluator as WF  # noqa: E402

RESULTS_TSV = os.path.join(ROOT, "auto_research", "results.tsv")
BASELINE_JSON = os.path.join(ROOT, "auto_research", "wf_baseline.json")

# 短縮版WFの期間
QUICK_ACCURACY_MONTHS = 6   # 直近6ヶ月のみ精度評価

# 採用判定の閾値
ROI_DEGRADATION_TOLERANCE = -10.0  # 副条件: 45日WF Det ROI 劣化 ≤ -10pt
TOP3_ACC_MIN_IMPROVEMENT = 0.0     # top3_acc は改善必須
BRIER_MIN_IMPROVEMENT = 0.0        # brier_1st は改善 (低下) 必須


def regenerate_features():
    """build_features.main() を呼び出して ml_features.csv を再生成"""
    print("[1/4] 特徴量を再生成中...", flush=True)
    import build_features
    importlib.reload(build_features)
    build_features.main()
    if not os.path.exists(WF.FEATURES_FILE):
        raise FileNotFoundError(f"{WF.FEATURES_FILE} が生成されませんでした")


def run_quick_accuracy(df, feature_cols):
    """直近 QUICK_ACCURACY_MONTHS ヶ月分だけ accuracy WF を回す"""
    cutoff = df["Date"].max() - pd.DateOffset(months=QUICK_ACCURACY_MONTHS)
    warmup = cutoff - pd.DateOffset(months=WF.ACC_WARMUP_MONTHS)
    df_a = df[df["Date"] >= warmup]
    if len(df_a) < 1000:
        return None, None
    weekly, monthly = WF.run_accuracy_walkforward(df_a, feature_cols, verbose=False)
    return weekly, monthly


def run_quick_roi(df, feature_cols):
    """45日WF Det モードを回す"""
    weekly = WF.run_roi_walkforward(df, feature_cols, mode="det", verbose=False)
    return weekly


def get_git_hash():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT
        ).decode().strip()
    except Exception:
        return "unknown"


def load_baseline():
    """wf_baseline.json を読み込んで返す。無ければ None"""
    if not os.path.exists(BASELINE_JSON):
        return None
    with open(BASELINE_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def judge_adoption(trial_acc, trial_roi, baseline):
    """採用判定。戻り値: (adopt: bool, reason: str)"""
    if baseline is None:
        return False, "baseline 未確定 (wf_baseline.json なし)"

    base_acc = baseline.get("accuracy", {})
    base_roi_det = baseline.get("roi", {}).get("det", {})

    # 主条件: accuracy 改善
    if not trial_acc:
        return False, "accuracy 評価結果なし"
    brier_diff = trial_acc.get("brier_1st", 999) - base_acc.get("brier_1st", 999)
    top3_diff = trial_acc.get("top3_acc", 0) - base_acc.get("top3_acc", 0)
    if brier_diff > -BRIER_MIN_IMPROVEMENT:
        # Brier は低い方が良い、ベースラインより低くないとNG
        return False, f"主条件NG: brier_1st diff={brier_diff:+.6f} (改善せず)"
    if top3_diff < TOP3_ACC_MIN_IMPROVEMENT:
        return False, f"主条件NG: top3_acc diff={top3_diff:+.4f} (改善せず)"

    # 副条件: ROI が大きく劣化していない
    if trial_roi:
        roi_diff = trial_roi.get("roi", 0) - base_roi_det.get("roi", 0)
        if roi_diff < ROI_DEGRADATION_TOLERANCE:
            return False, f"副条件NG: ROI diff={roi_diff:+.2f}pt (劣化過大)"

    return True, (f"採用: brier_1st {brier_diff:+.6f}, "
                  f"top3_acc {top3_diff:+.4f}, "
                  f"ROI diff {trial_roi.get('roi', 0) - base_roi_det.get('roi', 0):+.2f}pt")


def get_next_trial_id():
    if not os.path.exists(RESULTS_TSV):
        return 1
    try:
        df = pd.read_csv(RESULTS_TSV, sep="\t")
        if df.empty:
            return 1
        return int(df["trial_id"].max()) + 1
    except Exception:
        return 1


def append_result(trial_id, git_hash, trial_acc, trial_roi, adopt, reason, change_summary):
    """results.tsv にWF版1行追記"""
    header = [
        "trial_id", "timestamp", "git_hash",
        "brier_1st", "top3_acc", "log_loss_1st",
        "roi_45d", "n_trades_45d", "monthly_win_rate_45d",
        "is_kept", "adoption_reason",
        "change_summary",
    ]
    row = [
        str(trial_id),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        git_hash,
        f"{(trial_acc or {}).get('brier_1st', 0):.6f}",
        f"{(trial_acc or {}).get('top3_acc', 0):.4f}",
        f"{(trial_acc or {}).get('log_loss_1st', 0):.6f}",
        f"{(trial_roi or {}).get('roi', 0):.2f}",
        str((trial_roi or {}).get("n_trades", 0)),
        f"{(trial_roi or {}).get('monthly_win_rate', 0):.2f}",
        "1" if adopt else "0",
        reason.replace("\t", " ").replace("\n", " "),
        change_summary.replace("\t", " ").replace("\n", " "),
    ]
    need_header = not os.path.exists(RESULTS_TSV)
    with open(RESULTS_TSV, "a", encoding="utf-8") as f:
        if need_header:
            f.write("\t".join(header) + "\n")
        f.write("\t".join(row) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", type=str, default="(no note)",
                        help="build_features.py の変更内容を1行で")
    parser.add_argument("--skip-rebuild", action="store_true",
                        help="ml_features.csv を再生成せず既存を使う")
    args = parser.parse_args()

    start = datetime.now()
    os.chdir(ROOT)

    # 1. 特徴量再生成
    if not args.skip_rebuild:
        regenerate_features()
    else:
        print("[1/4] 特徴量再生成をスキップ")

    # 2. データ読込
    print("[2/4] データ読み込み...", flush=True)
    df, feature_cols = WF.load_features()
    print(f"    shape: {df.shape}, 特徴量: {len(feature_cols)} 個")

    # 3. WF評価 (accuracy + roi)
    print(f"[3/4] 短縮WF評価 (直近{QUICK_ACCURACY_MONTHS}ヶ月 accuracy + 45日 ROI Det)...", flush=True)
    weekly_a, monthly_a = run_quick_accuracy(df, feature_cols)
    trial_acc = WF.summarize_accuracy(weekly_a or [], monthly_a or [])

    weekly_r = run_quick_roi(df, feature_cols)
    trial_roi = WF.summarize_roi(weekly_r or [])

    # 4. 判定 + 記録
    print("[4/4] ベースライン比較と採用判定...", flush=True)
    baseline = load_baseline()
    adopt, reason = judge_adoption(trial_acc, trial_roi, baseline)

    trial_id = get_next_trial_id()
    git_hash = get_git_hash()
    append_result(trial_id, git_hash, trial_acc, trial_roi, adopt, reason, args.note)

    elapsed = (datetime.now() - start).total_seconds()
    print("\n" + "=" * 70)
    print(f" Trial #{trial_id} 完了 ({elapsed:.1f}秒)")
    print("=" * 70)
    print(f"  brier_1st   : {trial_acc.get('brier_1st', '-')}")
    print(f"  top3_acc    : {trial_acc.get('top3_acc', '-')}")
    print(f"  log_loss_1st: {trial_acc.get('log_loss_1st', '-')}")
    print(f"  ROI(45d Det): {trial_roi.get('roi', '-')}%")
    print(f"  n_trades(45d): {trial_roi.get('n_trades', '-')}")
    print(f"  月次勝率(45d): {trial_roi.get('monthly_win_rate', '-')}%")
    print(f"  判定        : {'[ADOPT]' if adopt else '[REJECT]'}")
    print(f"  理由        : {reason}")
    print(f"  記録先      : {RESULTS_TSV}")
    print("=" * 70)


if __name__ == "__main__":
    main()
