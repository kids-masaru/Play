"""
notify_loop_result.py
自己改善ループ終了後に LINE で結果サマリーを送信する。
run_loop.bat から呼ばれる。
"""
import os
import sys
import subprocess
import pandas as pd
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def safe_print(text):
    try:
        print(text)
    except Exception:
        try:
            print(text.encode("utf-8", errors="replace").decode("ascii", errors="replace"))
        except Exception:
            pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS_TSV = os.path.join(ROOT, "auto_research", "results.tsv")


def get_git_log_summary():
    """今日の実験コミット数を取得する"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        result = subprocess.check_output(
            ["git", "log", "--oneline", f"--since={today} 00:00", "--grep=exp #"],
            cwd=ROOT
        ).decode("utf-8", errors="replace").strip()
        commits = [l for l in result.splitlines() if l.strip()]
        return commits
    except Exception:
        return []


def build_message():
    """LINE に送るメッセージを組み立てる"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"🤖 自己改善ループ 完了レポート", f"実行時刻: {now}", ""]

    # results.tsv から今日の試行を集計
    if os.path.exists(RESULTS_TSV):
        try:
            df = pd.read_csv(RESULTS_TSV, sep="\t", dtype=str)
            for col in ["roi", "composite_score"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            df["n_trades"] = pd.to_numeric(df.get("n_trades", 0), errors="coerce").fillna(0).astype(int)
            df["is_kept"] = df.get("is_kept", "0").astype(str)

            total = len(df)
            improvements = int((df["is_kept"] == "1").sum())
            best = df.loc[df["composite_score"].idxmax()] if not df.empty else None

            lines.append(f"📊 累計試行数: {total} 回")
            lines.append(f"✅ 改善成功: {improvements} 回")
            if best is not None:
                lines.append(f"🏆 最高スコア: {best['composite_score']:.1f}")
                lines.append(f"   ROI: {best['roi']:.1f}%  取引: {best['n_trades']} 件")
                lines.append(f"   変更内容: {str(best.get('change_summary', ''))[:60]}")
        except Exception as e:
            lines.append(f"（結果の読み込みに失敗: {e}）")
    else:
        lines.append("（results.tsv が見つかりません）")

    # git コミット数
    commits = get_git_log_summary()
    lines.append("")
    lines.append(f"🔖 今日の改善コミット: {len(commits)} 件")
    for c in commits[:5]:
        lines.append(f"  {c[:60]}")
    if len(commits) > 5:
        lines.append(f"  ... 他 {len(commits) - 5} 件")

    return "\n".join(lines)


def send_line_message(message):
    """LINE Messaging API で送信"""
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.environ.get("LINE_USER_ID", "")
    if not token or not user_id:
        safe_print("[WARN] LINE_CHANNEL_ACCESS_TOKEN または LINE_USER_ID が未設定。通知をスキップします。")
        return False

    try:
        from linebot import LineBotApi
        from linebot.models import TextSendMessage
        api = LineBotApi(token)
        api.push_message(user_id, TextSendMessage(text=message))
        safe_print("[SUCCESS] LINE に送信しました。")
        return True
    except Exception as e:
        safe_print(f"[ERROR] LINE 送信失敗: {e}")
        return False


if __name__ == "__main__":
    # credentials.env を読み込む
    cred_path = os.path.join(ROOT, "credentials.env")
    if os.path.exists(cred_path):
        with open(cred_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

    msg = build_message()
    safe_print("--- 送信メッセージ ---")
    safe_print(msg)
    safe_print("---------------------")
    ok = send_line_message(msg)
    sys.exit(0 if ok else 2)
