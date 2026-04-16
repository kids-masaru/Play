"""
generate_loop_data.py
auto_research/results.tsv を読み、ダッシュボード用 JSON に変換する。
main_runner.py から毎日呼ばれる。
"""
import os
import json
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULTS_TSV = os.path.join(ROOT, "auto_research", "results.tsv")
OUTPUT_JSON = os.path.join(ROOT, "dashboard", "public", "daily_data", "loop_results.json")


def main():
    if not os.path.exists(RESULTS_TSV):
        data = {"trials": [], "best": None, "total_trials": 0, "total_improvements": 0}
    else:
        df = pd.read_csv(RESULTS_TSV, sep="\t", dtype=str)
        # 数値カラムを変換
        for col in ["roi", "hit_rate", "composite_score"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        for col in ["n_trades", "n_hits", "invest", "return", "trial_id"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

        if df.empty:
            best = None
            total_improvements = 0
        else:
            best_idx = df["composite_score"].idxmax()
            best = df.loc[best_idx].to_dict()
            total_improvements = int((df["is_kept"].astype(str) == "1").sum()) if "is_kept" in df.columns else 0

        # 最新50件のみ渡す（表示用）
        trials = df.tail(50).to_dict("records")
        data = {
            "trials": trials,
            "best": best,
            "total_trials": len(df),
            "total_improvements": total_improvements,
        }

    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"  loop_results.json を生成しました（試行: {data['total_trials']} 件 / 改善: {data['total_improvements']} 件）")


if __name__ == "__main__":
    main()
