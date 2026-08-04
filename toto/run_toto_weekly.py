"""toto 予測対戦の週次オーケストレーション。(T12 / F6)

毎日でも回せる冪等バッチ。実行内容（順序に意味あり）:
  1. collect_jleague.py        当年のJリーグ結果を更新（答え合わせ用）
  2. fetch_toto_round.py       販売中の回・対象試合・締切を取得 → round_*.json
  3. settle_results.py         終了済み試合の答え合わせ → settled_*.json
  4. predict_gemini.py <回号>  まだ予測していない回だけ Gemini 予測（quota節約・冪等）
                               ※統計モデルの確率も予測内に同梱される
  5. predict_codex.py <回号>   ChatGPT認証の Codex で未予測回を一括予測
  6. generate_toto_data.py     表示データ → dashboard/public/daily_data/toto_info.json
  7. git add/commit/push       GitHub Pages へ公開

壊れにくさ: スクレイピングや API が失敗しても全体は止めず、できたところまで公開する
（既存ボートの update_battle_dashboard.py と同方針）。

オプション:
  --no-push         git push しない（生成のみ。テスト用）
  --skip-gemini     Gemini 予測をスキップ（API を呼ばない）
  --skip-codex      Codex 予測をスキップ
  --force-predict   既に予測済みの回も予測し直す

前提: GEMINI_API_KEY を環境に展開した状態で実行（run_toto_weekly.bat 経由 / credentials.env）。
"""
import os
import sys
import io
import glob
import json
import subprocess
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TOTO_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOTO_DIR)                 # リポジトリ直下
DATA_DIR = os.path.join(TOTO_DIR, "data")
# 公開対象（REPO からの相対）。フロントの主データは toto_rounds.json（全回＋答え合わせ）で、
# toto_info.json は後方互換のフォールバック。両方 push しないと答え合わせが反映されない。
PUBLISH_FILES = [
    "dashboard/public/daily_data/toto_rounds.json",
    "dashboard/public/daily_data/toto_info.json",
]


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_py(script_rel, *args, allow_fail=False):
    """REPO 基準で toto/xxx.py をサブプロセス実行（失敗を局所化）。"""
    label = script_rel + ((" " + " ".join(args)) if args else "")
    log(f"実行: {label}")
    result = subprocess.run(
        [sys.executable, os.path.join(REPO, script_rel), *args],
        cwd=REPO, env=os.environ.copy(),
    )
    if result.returncode != 0:
        if allow_fail:
            log(f"  [WARN] {label} が exit={result.returncode}（続行）")
            return False
        raise RuntimeError(f"{label} が exit={result.returncode} で失敗")
    return True


def round_numbers(on_sale_only=False):
    """ローカルにある round_*.json の回号一覧。

    Codexの新規参加時に過去回を後付け予測しないよう、
    on_sale_only=True では今日以降が締切の回だけを返す。
    """
    nums = []
    today = datetime.now().date().isoformat()
    for p in glob.glob(os.path.join(DATA_DIR, "round_*.json")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if on_sale_only:
                deadlines = [
                    str(section.get("deadline", ""))[:10]
                    for section in (payload.get("kuji") or {}).values()
                    if section and section.get("deadline")
                ]
                if not any(deadline >= today for deadline in deadlines):
                    continue
            nums.append(payload["round"])
        except Exception:
            pass
    return sorted(nums)


def publish(no_push=False):
    """toto の表示データ（toto_rounds.json / toto_info.json）を git add -> commit -> push。"""
    if no_push:
        log("--no-push 指定のため公開（push）はスキップ")
        return
    exist = [f for f in PUBLISH_FILES if os.path.exists(os.path.join(REPO, f))]
    if not exist:
        log(f"  [WARN] 公開対象が無い: {PUBLISH_FILES}")
        return
    log("GitHub へ公開...")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.run(["git", "add", *exist], cwd=REPO, env=env)
    msg = f"Auto-update toto dashboard: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commit = subprocess.run(["git", "commit", "-m", msg, "--no-verify"],
                            cwd=REPO, env=env, capture_output=True, text=True)
    combined = (commit.stdout or "") + (commit.stderr or "")
    if commit.returncode == 0:
        log("  新規コミット作成")
    elif "nothing to commit" in combined:
        log("  コミット対象なし（変化なし）")
    else:
        log(f"  [WARN] commit: {combined.strip()[:200]}")
    push = subprocess.run(["git", "push", "origin", "main"],
                          cwd=REPO, env=env, capture_output=True, text=True)
    if push.returncode == 0:
        log("  push 完了（GitHub Pages へ反映）")
    else:
        log(f"  [WARN] push 失敗: {((push.stdout or '') + (push.stderr or '')).strip()[:200]}")


def main():
    no_push = "--no-push" in sys.argv
    skip_gemini = "--skip-gemini" in sys.argv
    skip_codex = "--skip-codex" in sys.argv
    force_predict = "--force-predict" in sys.argv

    t0 = datetime.now()
    log("===== toto 週次更新 開始 =====")

    # 1. Jリーグ結果更新（失敗しても続行）
    run_py("toto/collect_jleague.py", allow_fail=True)

    # 2. 販売中の回を取得（失敗したら以降は既存 round_*.json で続行）
    run_py("toto/fetch_toto_round.py", allow_fail=True)

    # 3. 先に答え合わせし、最新の結果を Codex の次回予測材料にする。
    run_py("toto/settle_results.py", allow_fail=True)

    # 4. 未予測の回だけ Gemini 予測
    if skip_gemini:
        log("--skip-gemini 指定のため Gemini 予測をスキップ")
    else:
        for n in round_numbers(on_sale_only=True):
            gem = os.path.join(DATA_DIR, f"gemini_round_{n}.json")
            if force_predict or not os.path.exists(gem):
                run_py("toto/predict_gemini.py", str(n), allow_fail=True)
            else:
                log(f"第{n}回はGemini予測済み（スキップ）")

    # 5. 未予測の回だけ Codex で一括予測（ChatGPT契約側の利用枠）
    if skip_codex:
        log("--skip-codex 指定のため Codex 予測をスキップ")
    else:
        for n in round_numbers(on_sale_only=True):
            codex = os.path.join(DATA_DIR, f"codex_round_{n}.json")
            if force_predict or not os.path.exists(codex):
                run_py("toto/predict_codex.py", str(n), allow_fail=True)
            else:
                log(f"第{n}回はCodex予測済み（スキップ）")

    # 6. 表示データ生成
    run_py("toto/generate_toto_data.py", allow_fail=True)

    # 7. 公開
    publish(no_push=no_push)

    log(f"===== 完了（所要 {datetime.now() - t0}） =====")


if __name__ == "__main__":
    main()
