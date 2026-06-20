"""Claude先生用: build_dataset と同じ選び方で 1000レースの「状況＋実結果」を取り出す。
LLMは呼ばず素材だけ用意する。各エージェントが読みやすいよう batch ファイルにも分割する。

出力:
  gemma_finetune/data/claude_src.jsonl            1行 = {"id","situation","result","payout"}
  gemma_finetune/data/claude_batches/batch_NN.json  50件ずつのバッチ(エージェント用)

使い方:
  python gemma_finetune/data/dump_situations.py            # 既定 1000
  python gemma_finetune/data/dump_situations.py 1000 50    # 件数 と バッチサイズ
"""
import os
import sys
import re
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# build_dataset の素材組み立てロジックを再利用（同じ選び方＝Gemini版と揃える）
import build_dataset as bd

OUT_JSONL = os.path.join(HERE, "claude_src.jsonl")
BATCH_DIR = os.path.join(HERE, "claude_batches")


def main():
    args = [a for a in sys.argv[1:] if a.isdigit()]
    n_target = int(args[0]) if len(args) >= 1 else 1000
    batch_size = int(args[1]) if len(args) >= 2 else 50

    res, race, before = bd.load_inputs()
    res = res[res["Result"].astype(str).str.strip() != ""].copy()
    res = res.sort_values("Date", ascending=False)

    rows = []
    seen = set()
    for _, row in res.iterrows():
        if len(rows) >= n_target:
            break
        rid = row["ID"]
        if rid in seen:
            continue
        seen.add(rid)
        combo = bd.parse_combo(row["Result"])
        if not combo:
            continue
        ymd = str(rid).split("_")[0]
        if not re.fullmatch(r"\d{8}", ymd):
            continue
        odds_df = bd.odds_for_date(ymd)
        situation = bd.build_situation(rid, race, before, odds_df)
        if not situation:
            continue
        rows.append({"id": rid, "situation": situation,
                     "result": combo, "payout": str(row.get("Payout", ""))})

    with open(OUT_JSONL, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    os.makedirs(BATCH_DIR, exist_ok=True)
    # 既存バッチを掃除
    for old in os.listdir(BATCH_DIR):
        if old.startswith("batch_") and old.endswith(".json"):
            os.remove(os.path.join(BATCH_DIR, old))
    n_batches = (len(rows) + batch_size - 1) // batch_size
    for i in range(n_batches):
        chunk = rows[i * batch_size:(i + 1) * batch_size]
        with open(os.path.join(BATCH_DIR, f"batch_{i:02d}.json"), "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=1)

    print(f"完了: {len(rows)} 件 → {OUT_JSONL}")
    print(f"バッチ: {n_batches} 個 (各最大{batch_size}件) → {BATCH_DIR}")


if __name__ == "__main__":
    main()
