# T11: gakushu-zen (su no gemma-3-1b) vs gakushu-go (LoRA) wo onaji race de hikaku.
import json, os, torch
from unsloth import FastLanguageModel
from unsloth.chat_templates import get_chat_template
from peft import PeftModel

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "train.jsonl")
ADAPTER = os.path.join(HERE, "lora_boat")
BASE = "unsloth/gemma-3-1b-it"
N = 2
INSTRUCTION = "次のボートレースを分析し、3連単(1着-2着-3着)の推論と買い目を答えてください。\n\n"
BAR = "=" * 70

model, tok = FastLanguageModel.from_pretrained(model_name=BASE, max_seq_length=1024, load_in_4bit=True)
tok = get_chat_template(tok, chat_template="gemma-3")
model = PeftModel.from_pretrained(model, ADAPTER)
FastLanguageModel.for_inference(model)

def gen(instruction):
    prompt = tok.apply_chat_template(
        [{"role": "user", "content": INSTRUCTION + instruction}],
        tokenize=False, add_generation_prompt=True)
    ids = tok(prompt, return_tensors="pt").to("cuda")
    out = model.generate(**ids, max_new_tokens=400, do_sample=False)
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()

rows = [json.loads(l) for l in open(DATA, encoding="utf-8")][:N]
for i, ex in enumerate(rows, 1):
    head = ex["instruction"].split("\n【出走表】")[0]
    print("\n" + BAR + "\n[ RACE " + str(i) + " ] " + head + "\n" + BAR, flush=True)
    with model.disable_adapter():
        before = gen(ex["instruction"])
    after = gen(ex["instruction"])
    teacher = ex["output"][:500]
    print("\n--- [学習前] 素のgemma-3-1b ---\n" + before, flush=True)
    print("\n--- [学習後] 微調整版 ---\n" + after, flush=True)
    print("\n--- [お手本] Gemini教師データ ---\n" + teacher, flush=True)
