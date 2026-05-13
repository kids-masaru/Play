"""
walkforward_baseline.py - ベースライン確定スクリプト

experiment_wf.py と同じ短縮版WFを実行してベースライン値を確定する。
(直近6ヶ月の accuracy WF + 45日の Det ROI)

設計上の理由:
  experiment_wf.py は試行時間短縮のため短縮版WFを使う。
  比較のためベースラインも同じスコープで計算する必要がある。
  フル2年WF結果は wf_model_results.csv に別途残るので参照可能。

使用法:
    1. walkforward_evaluator.py --mode roi (45日WF Det/LLM CSV出力)
    2. python auto_research/walkforward_baseline.py
       (短縮版acc WFを内部実行 + 既存45日WF ROI CSVを統合)

自己改善ループ (experiment_wf.py) はこの wf_baseline.json を読み、
試行スコアと比較して採用判定する。
"""
import argparse
import os
import sys
import json
import shutil
from datetime import datetime

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from auto_research import walkforward_evaluator as WF  # noqa: E402
from auto_research import experiment_wf as EWF  # noqa: E402

MODEL_CSV = os.path.join(ROOT, "auto_research", "wf_model_results.csv")
ROI_CSV = os.path.join(ROOT, "auto_research", "wf_roi_results.csv")
BASELINE_JSON = os.path.join(ROOT, "auto_research", "wf_baseline.json")


def load_accuracy_summary():
    """wf_model_results.csv から accuracy summary を再構築"""
    if not os.path.exists(MODEL_CSV):
        return None
    df = pd.read_csv(MODEL_CSV)
    if df.empty:
        return None
    weekly_rows = df.to_dict("records")
    # 月次は別途集計し直し
    monthly_rows = []
    if "month" in df.columns:
        for month, grp in df.groupby("month"):
            total_n = grp["n_races"].sum()
            if total_n == 0:
                continue
            wm = {"month": month, "n_races": int(total_n)}
            for col in ["brier_1st", "brier_2nd", "brier_3rd",
                        "log_loss_1st", "log_loss_2nd", "log_loss_3rd",
                        "top1_acc", "top3_acc"]:
                if col in grp.columns:
                    wm[col] = round(float((grp[col] * grp["n_races"]).sum() / total_n), 6)
            monthly_rows.append(wm)
    return WF.summarize_accuracy(weekly_rows, monthly_rows)


def load_roi_summary():
    """wf_roi_results.csv から mode別の roi summary を構築"""
    if not os.path.exists(ROI_CSV):
        return {}
    df = pd.read_csv(ROI_CSV)
    if df.empty:
        return {}
    result = {}
    if "mode" in df.columns:
        for mode, grp in df.groupby("mode"):
            weekly_rows = grp.to_dict("records")
            result[str(mode)] = WF.summarize_roi(weekly_rows)
    else:
        weekly_rows = df.to_dict("records")
        result["det"] = WF.summarize_roi(weekly_rows)
    return result


def print_section(label, d):
    print(f"\n[{label}]")
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for kk, vv in v.items():
                print(f"    {kk}: {vv}")
        else:
            print(f"  {k}: {v}")


def compute_quick_accuracy_baseline():
    """experiment_wf.py と同じ短縮版WF (直近6ヶ月) で accuracy ベースラインを取る"""
    print("[run] 短縮版WF (直近6ヶ月 accuracy) を実行中...")
    df, feature_cols = WF.load_features()
    weekly, monthly = EWF.run_quick_accuracy(df, feature_cols)
    if not weekly:
        return None
    return WF.summarize_accuracy(weekly, monthly)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-csv", action="store_true",
                        help="短縮版WFを再実行せず、既存CSV から構築する (旧挙動)")
    args = parser.parse_args()

    if not args.from_csv and not os.path.exists(ROI_CSV):
        print("[ERROR] wf_roi_results.csv が無い")
        print("  先に walkforward_evaluator.py --mode roi を実行してください")
        sys.exit(1)

    print("=" * 70)
    print(" ベースライン構築 (短縮版WFで実行)")
    print("=" * 70)

    if os.path.exists(BASELINE_JSON):
        backup = BASELINE_JSON + f".bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.copy(BASELINE_JSON, backup)
        print(f"[INFO] 既存ベースラインをバックアップ -> {backup}")

    if args.from_csv:
        acc = load_accuracy_summary()
    else:
        acc = compute_quick_accuracy_baseline()
    roi = load_roi_summary()

    baseline = {
        "confirmed_at": datetime.now().isoformat(),
        "accuracy_source": "quick_walkforward (直近6ヶ月)" if not args.from_csv else "wf_model_results.csv (フル2年)",
        "roi_source": "wf_roi_results.csv (45日WF)",
        "accuracy": acc or {},
        "roi": roi or {},
    }
    with open(BASELINE_JSON, "w", encoding="utf-8") as f:
        json.dump(baseline, f, ensure_ascii=False, indent=2)

    print(f"\n-> {BASELINE_JSON}")

    if acc:
        print_section("accuracy (2年WF 加重平均)", {
            k: v for k, v in acc.items() if not isinstance(v, dict)
        })
    if roi:
        for mode, d in roi.items():
            print_section(f"roi.{mode} (45日WF)", {
                k: v for k, v in d.items() if not isinstance(v, dict)
            })

    print("\n次のステップ: experiment_wf.py が このベースラインを参照します。")


if __name__ == "__main__":
    main()
