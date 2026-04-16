"""
baseline.py - 初期ベースライン測定

現状の build_features.py でモデルを学習・評価し、
results.tsv に初期値（trial_id=1）を記録する。

自己改善ループを開始する前の1回だけ実行すること。
"""
import sys
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    print("=" * 60)
    print(" BASELINE 測定スタート")
    print("=" * 60)
    print("現状の build_features.py でモデルを学習し、初期スコアを記録します。\n")

    cmd = [
        sys.executable,
        os.path.join("auto_research", "experiment.py"),
        "--note", "baseline (初期スコア)",
    ]
    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode != 0:
        print("\n[ERROR] experiment.py が失敗しました。終了コード:", result.returncode)
        sys.exit(result.returncode)

    print("\n[DONE] ベースライン測定完了。")
    print("  次のステップ: Claude Code 新セッションで @auto_research/program.md を読ませて本番ループ開始")


if __name__ == "__main__":
    main()
