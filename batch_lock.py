"""バッチどうしが重ならないようにする小さな目印（ロック）。

夜（run_daily.bat）・朝（run_morning.bat）・締切（run_closing.bat）が同時に動くと、
ローカルAIや Claude / Codex を取り合って全部が遅くなる（2026-10-19 に実際に起きた）。
そこで各バッチは始まりに `start`、終わりに `end` を呼び、
「動いている間だけ logs/locks/<名前>.lock がある」状態にする。
後から始まるバッチは `--wait-for` で、相手の目印が消えるまで待つ。

使い方（.bat から）:
    python batch_lock.py start daily --wait-for closing morning --max-wait-minutes 180
    ...本体...
    python batch_lock.py end daily

方針:
- 何があってもバッチ本体を止めない（いつも終了コード0）。待ち時間の上限を過ぎたら、警告を出して始める。
- 目印を書いたバッチ（cmd.exe）がもう居なければ、目印は古いものとして無視する（途中で落ちた場合の対策）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil
except ImportError:  # psutil が無くても「時間だけで古さを判定」して動く
    psutil = None

ROOT = Path(__file__).resolve().parent
DEFAULT_LOCK_DIR = ROOT / "logs" / "locks"
POLL_SECONDS = 60
REPORT_EVERY_MINUTES = 10
# これより古い目印は、プロセスが確かめられなくても古いものとみなす
STALE_HOURS = 30


def now() -> datetime:
    return datetime.now()


def log(message: str) -> None:
    print(f"[batch_lock {now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def owner_process() -> tuple[int, float | None]:
    """目印の持ち主＝この python を起動した .bat（cmd.exe）の PID と起動時刻を返す。"""
    if psutil is None:
        return os.getppid(), None
    try:
        me = psutil.Process()
        for parent in me.parents():
            if parent.name().lower() == "cmd.exe":
                return parent.pid, parent.create_time()
        parent = me.parent()
        if parent is not None:
            return parent.pid, parent.create_time()
    except psutil.Error:
        pass
    return os.getppid(), None


def lock_path(name: str, lock_dir: Path) -> Path:
    return lock_dir / f"{name}.lock"


def read_lock(name: str, lock_dir: Path) -> dict | None:
    path = lock_path(name, lock_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # 壊れた目印は「動いていない」扱い（待ち続けて止まるよりよい）
        return None


def is_alive(lock: dict | None) -> bool:
    """目印の持ち主のバッチがまだ動いているか。"""
    if not lock:
        return False
    try:
        started = datetime.fromisoformat(lock["started_at"])
    except (KeyError, TypeError, ValueError):
        return False
    if now() - started > timedelta(hours=STALE_HOURS):
        return False
    pid = lock.get("pid")
    if psutil is None or not isinstance(pid, int):
        return True
    try:
        proc = psutil.Process(pid)
        created = lock.get("process_created")
        # PID は使い回されるので、起動時刻も同じかを見る
        if isinstance(created, (int, float)) and abs(proc.create_time() - created) > 2:
            return False
        return proc.is_running()
    except psutil.Error:
        return False


def running_others(names: list[str], lock_dir: Path) -> list[str]:
    return [name for name in names if is_alive(read_lock(name, lock_dir))]


def wait_for(names: list[str], lock_dir: Path, max_wait_minutes: float,
              poll_seconds: float = POLL_SECONDS, sleep=time.sleep) -> dict:
    """相手のバッチが終わるまで待つ。上限を過ぎたら待つのをやめる。"""
    begin = time.monotonic()
    busy = running_others(names, lock_dir)
    if not busy:
        return {"waited_minutes": 0.0, "timed_out": False, "still_running": []}
    log(f"待ちます: {', '.join(busy)} がまだ動いています（上限 {max_wait_minutes:g} 分）")
    next_report = REPORT_EVERY_MINUTES
    while busy:
        waited = (time.monotonic() - begin) / 60
        if waited >= max_wait_minutes:
            log(f"⚠ 待ち時間の上限 {max_wait_minutes:g} 分を過ぎたので始めます（まだ動いている: {', '.join(busy)}）")
            return {"waited_minutes": round(waited, 1), "timed_out": True, "still_running": busy}
        if waited >= next_report:
            log(f"まだ待っています（{waited:.0f} 分経過）: {', '.join(busy)}")
            next_report += REPORT_EVERY_MINUTES
        sleep(poll_seconds)
        busy = running_others(names, lock_dir)
    waited = (time.monotonic() - begin) / 60
    log(f"待ち終わり（{waited:.1f} 分）")
    return {"waited_minutes": round(waited, 1), "timed_out": False, "still_running": []}


def write_lock(name: str, lock_dir: Path) -> dict:
    pid, created = owner_process()
    lock = {"name": name, "pid": pid, "process_created": created,
            "started_at": now().isoformat(timespec="seconds")}
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path(name, lock_dir).write_text(json.dumps(lock, ensure_ascii=False), encoding="utf-8")
    return lock


def remove_lock(name: str, lock_dir: Path) -> bool:
    try:
        lock_path(name, lock_dir).unlink()
        return True
    except FileNotFoundError:
        return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="バッチどうしが重ならないようにする目印")
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start", help="（必要なら待ってから）目印を置く")
    start.add_argument("name")
    start.add_argument("--wait-for", nargs="*", default=[], help="終わるのを待つ相手のバッチ名")
    start.add_argument("--max-wait-minutes", type=float, default=180)
    end = sub.add_parser("end", help="目印を外す")
    end.add_argument("name")
    for p in (start, end):
        p.add_argument("--lock-dir", type=Path, default=DEFAULT_LOCK_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "start":
            others = [n for n in args.wait_for if n != args.name]
            wait_for(others, args.lock_dir, args.max_wait_minutes)
            lock = write_lock(args.name, args.lock_dir)
            log(f"開始: {args.name}（pid={lock['pid']}）")
        else:
            removed = remove_lock(args.name, args.lock_dir)
            log(f"終了: {args.name}" + ("" if removed else "（目印はもうありませんでした）"))
    except Exception as exc:  # 目印の失敗でバッチ本体を止めない
        log(f"⚠ 目印の処理に失敗しました（バッチは続けます）: {exc!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
