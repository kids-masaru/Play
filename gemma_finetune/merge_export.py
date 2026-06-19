# LoRA wo base ni merge shite 16bit HF model toshite hozon (GGUF henkan no zen-dankai)
import os
from unsloth import FastLanguageModel
HERE = os.path.dirname(os.path.abspath(__file__))
ADAPTER = os.path.join(HERE, "lora_boat")
MERGED = os.path.join(HERE, "merged_16bit")
print("[merge] loading base+adapter ...", flush=True)
model, tok = FastLanguageModel.from_pretrained(model_name=ADAPTER, max_seq_length=1024, load_in_4bit=False)
print("[merge] saving merged 16bit to " + MERGED, flush=True)
model.save_pretrained_merged(MERGED, tok, save_method="merged_16bit")
print("[merge] DONE", flush=True)
