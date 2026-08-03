"""予測対戦ダッシュボードの当日データを生成して公開するオーケストレーション。

朝バッチ (run_morning.bat) の後に実行する想定。手動でも実行可。

やること:
  1. 必要な当日CSVを daily_data/ -> dashboard/public/daily_data/ にコピー
  2. generate_battle_data.py  (1回目: daily_race_info.json を生成)
  3. generate_gemini_predictions.py  (race_info.json を読んで Gemini 予測)
  4. predict_gemma_ft.py  (race_info.json を読んで 学習版Gemma 予測 / Ollama)
  5. generate_battle_data.py  (2回目: Gemini と 学習版Gemma を取り込んだ最終版)
  6. 成果物 JSON を git add -> commit -> push (GitHub Pages へ公開)

なぜこの順番か:
  generate_gemini は daily_race_info.json を入力に取り、
  generate_battle_data は daily_gemini_predictions.csv を任意入力に取る
  という相互依存があるため、battle_data を Gemini の前後で 2 回回す。

オプション:
  --no-push     : git push を行わない (生成のみ。テスト用)
  --skip-gemini : Gemini 予測をスキップ (API を呼ばない。テスト用)
  --skip-codex  : Codex 予測をスキップ (ChatGPT利用枠を使わない)
"""
import os
import sys
import io
import time
import shutil
import subprocess
from datetime import datetime

# Windows cmd の stdout が cp932 でも絵文字や日本語で落ちないように UTF-8 化
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(ROOT, "daily_data")                       # バッチが書き込む元
DST_DIR = os.path.join(ROOT, "dashboard", "public", "daily_data")  # 生成系が読む先

# generate_battle_data.py が DST_DIR から読む当日入力CSV
SOURCE_CSVS = [
    "daily_predictions.csv",      # AI(Det/LLM)の買い目・見解・ログ
    "daily_raw_race_data.csv",    # 出走表 (1行=1艇)
    "daily_raw_beforeinfo.csv",   # 直前情報 (1行=1レース)
    "daily_odds_3t.csv",          # 3連単オッズ (1行=1組合せ)
]

# 公開（push）対象。ダッシュボードが実際に fetch するファイル。
PUBLISH_FILES = [
    "dashboard/public/daily_data/daily_race_info.json",
    "dashboard/public/daily_data/ai_predictions_summary.json",
    "dashboard/public/daily_data/daily_codex_predictions.csv",
    # 予測対戦の「4者戦績」は結果CSVが要る。これが無いと本番で的中率が全部0になる。
    "dashboard/public/daily_data/daily_history_results.csv",
    # 傾向(攻略図)タブの会場別/レース番号別イン率ヒートマップ用
    "dashboard/public/daily_data/boat_tendency.json",
]


def log(msg):
    """進捗ログ（時刻つき）"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run_py(script, allow_fail=False, extra_args=None):
    """同一フォルダの Python スクリプトをサブプロセスで実行する。

    サブプロセス化する理由: generate_gemini は API キー未設定で sys.exit() するため、
    import で呼ぶと本体まで巻き込まれて落ちる。プロセス分離で失敗を局所化する。
    """
    cmd = [sys.executable, os.path.join(ROOT, script)] + (extra_args or [])
    log(f"実行: {script} {' '.join(extra_args or [])}")
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        if allow_fail:
            log(f"  [WARN] {script} が exit={result.returncode} で終了（続行）")
            return False
        raise RuntimeError(f"{script} が exit={result.returncode} で失敗しました")
    return True


def safe_copy(src, dst, retries=5, wait=1.0):
    """OneDrive 環境でも通るコピー。

    shutil.copy2 は既存 dst を CopyFile2 で直接上書きするため、OneDrive が
    同期中にロックしていると WinError 32 で落ちる。temp に書いて os.replace で
    アトミックに差し替えれば既存 dst を開かずに済むので回避できる。
    ロックが一瞬残るケースに備えてリトライも入れる。
    """
    tmp = dst + ".tmp"
    last_err = None
    for i in range(retries):
        try:
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(wait)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    raise last_err


def copy_sources():
    """当日CSVを SRC_DIR -> DST_DIR にコピー（穴①を埋める）"""
    log("当日CSVを dashboard/public/daily_data/ へコピー...")
    os.makedirs(DST_DIR, exist_ok=True)
    copied = 0
    for name in SOURCE_CSVS:
        src = os.path.join(SRC_DIR, name)
        dst = os.path.join(DST_DIR, name)
        if not os.path.exists(src):
            # daily_raw_beforeinfo は朝の時点で未生成のことがある（展示前）。警告のみ。
            log(f"  [WARN] 元ファイルなし（スキップ）: {name}")
            continue
        safe_copy(src, dst)
        copied += 1
        log(f"  copied: {name}")
    if copied == 0:
        raise RuntimeError("コピーできた当日CSVが1本もありません。朝バッチは実行済みですか？")


def publish(no_push=False):
    """成果物JSONを git add -> commit -> push（穴③を埋める）"""
    if no_push:
        log("--no-push 指定のため公開（push）はスキップします")
        return
    log("成果物を GitHub へ公開...")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    for f in PUBLISH_FILES:
        path = os.path.join(ROOT, f)
        if os.path.exists(path):
            subprocess.run(["git", "add", f], cwd=ROOT, env=env)
        else:
            log(f"  [WARN] 公開対象が見つかりません: {f}")

    msg = f"Auto-update battle dashboard: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    commit = subprocess.run(
        ["git", "commit", "-m", msg, "--no-verify"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    combined = (commit.stdout or "") + (commit.stderr or "")
    if commit.returncode == 0:
        log("  新規コミット作成")
    elif "nothing to commit" in combined:
        log("  コミット対象なし（内容に変化なし）")
    else:
        log(f"  [WARN] commit 失敗: {combined.strip()[:200]}")

    push = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    if push.returncode == 0:
        log("  push 完了（GitHub Pages へ反映）")
    else:
        log(f"  [WARN] push 失敗: {((push.stdout or '') + (push.stderr or '')).strip()[:200]}")


def main():
    no_push = "--no-push" in sys.argv
    skip_gemini = "--skip-gemini" in sys.argv
    skip_grok = "--skip-grok" in sys.argv
    skip_codex = "--skip-codex" in sys.argv
    skip_gemma = "--skip-gemma" in sys.argv  # 学習版Gemma(Ollama)をスキップ

    t0 = datetime.now()
    log("===== 予測対戦ダッシュボード更新 開始 =====")

    # 穴①: コピー
    copy_sources()

    # 穴②: 生成（正しい順序で）
    # 1回目: Gemini 抜きで daily_race_info.json を作る（Gemini の入力になる）
    run_py("generate_battle_data.py")

    if skip_gemini:
        log("--skip-gemini 指定のため Gemini 予測をスキップ")
    else:
        # Gemini 予測（quota 超過等で失敗しても、Det/LLM だけで公開を続行する）
        run_py("generate_gemini_predictions.py", allow_fail=True)

    if skip_grok:
        log("--skip-grok specified; Grok prediction skipped")
    else:
        # API key 未設定・一時的なAPI障害は、他の対戦者と公開を止めない。
        run_py("generate_grok_predictions.py", allow_fail=True)

    if skip_codex:
        log("--skip-codex specified; Codex prediction skipped")
    else:
        run_py("generate_codex_predictions.py", allow_fail=True)

    # 学習版Gemma 予測（Ollama 未起動/未登録でも、他を止めず続行）
    # 2モデル: Gemini先生版(gemma-boat:1b) と Claude先生版(gemma-boat-claude:1b)
    if skip_gemma:
        log("--skip-gemma 指定のため 学習版Gemma 予測をスキップ")
    else:
        run_py("predict_gemma_ft.py", allow_fail=True)  # Gemini先生版(既定)
        run_py("predict_gemma_ft.py", allow_fail=True, extra_args=[
            "--model", "gemma-boat-claude:1b",
            "--out", "daily_gemma_claude_predictions.csv",
            "--tag", "GemmaClaude"])  # Claude先生版
        run_py("predict_gemma_ft.py", allow_fail=True, extra_args=[
            "--model", "gemma-boat-grok-x:1b",
            "--out", "daily_gemma_grok_x_predictions.csv",
            "--tag", "GemmaGrokX"])

    # 2回目: Gemini と 学習版Gemma を取り込んだ最終版
    # （--skip-gemini かつ --skip-gemma でも、再生成は無害なので常に回す）
    run_py("generate_battle_data.py")

    # 傾向(攻略図)タブのデータを再生成（会場別/レース番号別のイン率ヒートマップ）。
    # 最新の結果・予想CSVが揃った後に集計する。失敗しても他の公開は止めない。
    run_py("analysis/boat_venue_tendency.py", allow_fail=True)

    # 穴③: 公開
    publish(no_push=no_push)

    dur = datetime.now() - t0
    log(f"===== 完了（所要 {dur}） =====")


if __name__ == "__main__":
    main()
