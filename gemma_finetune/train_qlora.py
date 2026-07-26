"""Gemma 2B を QLoRA で微調整する（WSL2 + RTX A3000 6GB 想定）。(T8/T9)

入力 : ~/gemma-ft/data/train.jsonl  （{"instruction":..,"output":..}）
出力 : ~/gemma-ft/outputs/          （学習ログ・チェックポイント）
       ~/gemma-ft/lora_boat/        （学習済み LoRA アダプタ）

ポイント:
- 4bit QLoRA（6GBに収める）。loss を毎ステップ表示＝「学習が進む」のを見るため。
- 学習後、サンプル1件で生成して「学習後の話し方」を確認。

実行（WSL内）:
  ~/gemma-ft/venv/bin/python ~/gemma-ft/train_qlora.py
  ~/gemma-ft/venv/bin/python ~/gemma-ft/train_qlora.py --epochs 3
"""
import os
import sys
import argparse
import torch
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig

MAX_SEQ = 1024
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "train.jsonl")
OUT = os.path.join(HERE, "outputs")
ADAPTER = os.path.join(HERE, "lora_boat")
# Gemma2 は transformers5.5+unsloth で壊れるため Gemma3-1b を採用（この環境で生成確認済み）
BASE = "unsloth/gemma-3-1b-it"
CHAT_TEMPLATE = "gemma-3"

INSTRUCTION = "次のボートレースを分析し、3連単(1着-2着-3着)の推論と買い目を答えてください。\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--data", default=DATA, help="学習JSONLのパス")
    ap.add_argument("--out", default=OUT, help="チェックポイント出力先")
    ap.add_argument("--adapter", default=ADAPTER, help="LoRAアダプタ出力先")
    args = ap.parse_args()

    print(f"=== Gemma QLoRA 微調整 開始 (epochs={args.epochs}) ===", flush=True)
    model, tok = FastLanguageModel.from_pretrained(
        model_name=BASE, max_seq_length=MAX_SEQ, load_in_4bit=True)
    # チャットテンプレートを正式に設定（応答マスクの目印を揃えるため）
    tok = get_chat_template(tok, chat_template=CHAT_TEMPLATE)

    # LoRA アダプタを差す（学習するのはこの小さな追加重みだけ＝省メモリ・高速）
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=42)

    # データを Gemma のチャット形式に整形
    def fmt(ex):
        msgs = [
            {"role": "user", "content": INSTRUCTION + ex["instruction"]},
            {"role": "assistant", "content": ex["output"]},
        ]
        return {"text": tok.apply_chat_template(msgs, tokenize=False)}

    ds = load_dataset("json", data_files=args.data, split="train").map(fmt)
    print(f"学習データ: {len(ds)} 件", flush=True)

    cfg = SFTConfig(
        dataset_text_field="text",
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        warmup_steps=5,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        logging_steps=1,          # 毎ステップ loss を表示
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir=args.out,
        report_to="none",
    )
    trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=ds, args=cfg)

    # 応答(model側)だけで損失を計算する。プロンプト(出走表など)はマスク。
    # → 「お手本の答え方」を学ばせる。loss も正常域に収まる。
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<start_of_turn>user\n",
        response_part="<start_of_turn>model\n",
    )

    stats = trainer.train()
    print(f"\n=== 学習完了 ===", flush=True)
    print(f"最終 train loss: {stats.training_loss:.4f}", flush=True)

    model.save_pretrained(args.adapter)
    tok.save_pretrained(args.adapter)
    print(f"LoRAアダプタ保存: {args.adapter}", flush=True)

    # 学習後の話し方を1件だけ確認（サンプル入力で生成）
    sample = ds[0]["instruction"] if False else None
    try:
        import json
        first = json.loads(open(args.data, encoding="utf-8").readline())
        prompt = tok.apply_chat_template(
            [{"role": "user", "content": INSTRUCTION + first["instruction"]}],
            tokenize=False, add_generation_prompt=True)
        FastLanguageModel.for_inference(model)
        ids = tok(prompt, return_tensors="pt").to("cuda")
        out = model.generate(**ids, max_new_tokens=256, temperature=0.7, do_sample=True)
        text = tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True)
        print("\n=== 学習後モデルの生成サンプル ===", flush=True)
        print(text[:800], flush=True)
    except Exception as e:
        print(f"(サンプル生成スキップ: {type(e).__name__}: {e})", flush=True)


if __name__ == "__main__":
    main()
