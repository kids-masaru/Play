# -*- coding: utf-8 -*-
"""Grok+X教材のクリーニング。

train_grok_x_ranked.jsonl の output 冒頭にある
「[推論]\n（まずXで…検索します 等のメタ前置き）」を除去し、
【案1】から始まる形に正規化して train_grok_x_cleaned.jsonl を出力する。
教材内容（案1〜3の推論・買い目）は一切変更しない。
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SRC = "gemma_finetune/data/train_grok_x_ranked.jsonl"
DST = "gemma_finetune/data/train_grok_x_cleaned.jsonl"

cleaned = 0
total = 0
with open(SRC, encoding="utf-8") as f, open(DST, "w", encoding="utf-8") as out:
    for line in f:
        total += 1
        ex = json.loads(line)
        output = ex["output"]
        # 【案1】より前にメタ前置き（検索します等）がある場合は【案1】以降だけ残す
        idx = output.find("【案1】")
        if idx > 0:
            head = output[:idx]
            if "検索します" in head or "検索した" in head:
                output = output[idx:]
                cleaned += 1
        ex["output"] = output
        out.write(json.dumps(ex, ensure_ascii=False) + "\n")

print(f"総数: {total} 件 / 前置き除去: {cleaned} 件")
print(f"出力: {DST}")
