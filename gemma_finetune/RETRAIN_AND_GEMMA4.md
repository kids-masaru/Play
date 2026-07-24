# 再学習と Gemma 4 E2B の検証手順

既存の `gemma-boat:1b` と `gemma-boat-claude:1b` は上書きしない。
新しいモデル名（例: `gemma-boat-gemini-202607`）で評価してから採用する。

## 1. Gemini先生版

`GEMINI_API_KEY` を設定した環境で、最新の教師データを作成する。

```powershell
python gemma_finetune/data/build_dataset.py 1000
```

作成された `train.jsonl` を日付付きで退避し、WSL の QLoRA 環境で学習する。

```bash
~/gemma-ft/venv/bin/python ~/gemma-ft/train_qlora.py --epochs 2
```

## 2. Claude先生版

`dump_situations.py` で同じ母集団の状況データを出し、Claudeに教師回答を生成させて
`train_claude.jsonl` を作る。Gemini版と同じ件数・同じデータ期間で揃える。

```powershell
python gemma_finetune/data/dump_situations.py 1000 50
```

その後、Claude教師データを指定して同じQLoRA学習を行う。

## 3. Gemma 4 E2B 最小QLoRAテスト

RTX A3000 6GBでは、推論で動いても学習時にOOMになる可能性が高い。
最初は本学習をせず、以下の条件だけで1ステップのメモリ確認をする。

- ベース: `google/gemma-4-E2B-it`
- 4bit QLoRA、batch size 1、gradient checkpointing 有効
- 最大入力長 256、LoRA rank 8
- 学習データ 8件、1 step

成功しても、長い競艇プロンプトと1000件学習が通るかは別途確認する。
OOMならGemma 3 1Bの再学習を正式版とし、Gemma 4には12GB以上のGPUを使う。

## 4. 採用条件

新旧モデルを同じ未学習レースで比較する。文章の自然さではなく、買い目の的中率・ROI・
予測失敗率を記録し、十分なレース数で既存版を上回った場合だけ朝バッチのモデル名を切り替える。
