"""Qwen3 1.7B を QLoRA で微調整する（WSL2 + RTX A3000 6GB 想定）。

train_qlora.py（Gemma版）をベースに、Qwen3向けに以下を変更:
- ベースモデル: unsloth/Qwen3-1.7B
- チャットテンプレート: qwen3-instruct（ChatML形式・思考ブロックなし）
- 応答マスクの目印: <|im_start|>user / <|im_start|>assistant
学習データ・ハイパーパラメータはGemma弟子と同一（フェア比較のため）。

実行（WSL内）:
  ~/gemma-ft/venv/bin/python ~/gemma-ft/train_qlora_qwen.py --data ~/gemma-ft/data/train_claude.jsonl --epochs 2
"""
import os
import argparse
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template, train_on_responses_only
from datasets import load_dataset
from trl import SFTTrainer, SFTConfig

MAX_SEQ = 1024
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "train_claude.jsonl")
OUT = os.path.join(HERE, "outputs_qwen")
ADAPTER = os.path.join(HERE, "lora_boat_qwen_claude")
BASE = "unsloth/Qwen3-1.7B"
CHAT_TEMPLATE = "qwen3-instruct"

# Gemma版と同一の指示文（フェア比較のため変更しない）
INSTRUCTION = "次のボートレースを分析し、3連単(1着-2着-3着)の推論と買い目を答えてください。\n\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--data", default=DATA, help="学習JSONLのパス")
    ap.add_argument("--out", default=OUT, help="チェックポイント出力先")
    ap.add_argument("--adapter", default=ADAPTER, help="LoRAアダプタ出力先")
    args = ap.parse_args()

    print(f"=== Qwen3 1.7B QLoRA 微調整 開始 (epochs={args.epochs}) ===", flush=True)
    model, tok = FastLanguageModel.from_pretrained(
        model_name=BASE, max_seq_length=MAX_SEQ, load_in_4bit=True)
    tok = get_chat_template(tok, chat_template=CHAT_TEMPLATE)

    # LoRA アダプタ（Gemma版と同一設定: r=16, alpha=16）
    model = FastLanguageModel.get_peft_model(
        model, r=16, lora_alpha=16, lora_dropout=0.0,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        use_gradient_checkpointing="unsloth", random_state=42)

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
        logging_steps=1,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir=args.out,
        report_to="none",
    )
    trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=ds, args=cfg)

    # 応答(assistant側)だけで損失を計算。プロンプト(出走表)はマスク。
    trainer = train_on_responses_only(
        trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )

    stats = trainer.train()
    print(f"\n=== 学習完了 ===", flush=True)
    print(f"最終 train loss: {stats.training_loss:.4f}", flush=True)

    model.save_pretrained(args.adapter)
    tok.save_pretrained(args.adapter)
    print(f"LoRAアダプタ保存: {args.adapter}", flush=True)

    # 学習後の話し方を1件だけ確認
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
