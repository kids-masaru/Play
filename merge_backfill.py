"""past_odds_3t_backfill/ の全日別CSVを past_odds_3t.csv にストリーミング統合。

- 既存 past_odds_3t.csv は past_odds_3t_pre_backfill.csv にバックアップ
- 日別ファイル名(YYYYMMDD.csv)順 = 時系列順 で結合
- ヘッダは1回だけ、ストリーミング書き込み(メモリ最小)
"""
import os
import shutil
import time
from glob import glob

BACKFILL_DIR = os.path.join("past_data", "past_odds_3t_backfill")
TARGET_CSV = os.path.join("past_data", "past_odds_3t.csv")
BACKUP_CSV = os.path.join("past_data", "past_odds_3t_pre_backfill.csv")


def main():
    t0 = time.time()

    # 1) バックアップ
    if os.path.exists(TARGET_CSV):
        print(f"[1/3] 既存ファイルをバックアップ: {TARGET_CSV} -> {BACKUP_CSV}")
        shutil.copy2(TARGET_CSV, BACKUP_CSV)
        old_size = os.path.getsize(TARGET_CSV)
        print(f"    元サイズ: {old_size/1024/1024:.1f} MB")
    else:
        print("[1/3] 既存 past_odds_3t.csv なし、バックアップスキップ")

    # 2) 日別CSV列挙
    files = sorted(glob(os.path.join(BACKFILL_DIR, "*.csv")))
    files = [f for f in files if os.path.basename(f) != "no_race.txt"]
    print(f"[2/3] 統合対象: {len(files)} ファイル")
    if not files:
        print("    対象なし、終了")
        return

    # 3) ストリーミング結合
    tmp = TARGET_CSV + ".tmp"
    total_rows = 0
    with open(tmp, "w", encoding="utf-8", newline="") as fout:
        header_written = False
        for i, fpath in enumerate(files, 1):
            with open(fpath, "r", encoding="utf-8") as fin:
                header = fin.readline()
                if not header_written:
                    fout.write(header)
                    header_written = True
                rows_this = 0
                for line in fin:
                    fout.write(line)
                    rows_this += 1
                total_rows += rows_this
            if i % 50 == 0 or i == len(files):
                elapsed = time.time() - t0
                print(f"    [{i:3d}/{len(files)}] {os.path.basename(fpath)} +{rows_this} (累計 {total_rows:,}行, {elapsed:.1f}s)")

    # 4) アトミックrename
    os.replace(tmp, TARGET_CSV)
    new_size = os.path.getsize(TARGET_CSV)
    elapsed = time.time() - t0
    print(f"\n[3/3] 完了")
    print(f"    出力: {TARGET_CSV}")
    print(f"    総行数: {total_rows:,}")
    print(f"    サイズ: {new_size/1024/1024:.1f} MB")
    print(f"    所要時間: {elapsed:.1f} 秒")


if __name__ == "__main__":
    main()
