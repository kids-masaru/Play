# LoRA wo base ni merge shite 16bit HF model toshite hozon (GGUF henkan no zen-dankai)
import os
import argparse
from unsloth import FastLanguageModel
HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTER = os.path.join(HERE, "lora_boat")
MERGED = os.path.join(HERE, "merged_16bit")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default=ADAPTER, help="LoRAアダプタのパス")
    parser.add_argument("--merged", default=MERGED, help="16bitマージ先")
    args = parser.parse_args()
    print("[merge] loading base+adapter ...", flush=True)
    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.adapter, max_seq_length=1024, load_in_4bit=False)
    print("[merge] saving merged 16bit to " + args.merged, flush=True)
    model.save_pretrained_merged(args.merged, tok, save_method="merged_16bit")
    print("[merge] DONE", flush=True)


if __name__ == "__main__":
    main()
