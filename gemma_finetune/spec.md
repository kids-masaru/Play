# Gemma ローカル微調整 — 学習体験プロジェクト spec

> **モデル変更履歴（2026-06-19）**: 当初は Gemma 2-2b を予定したが、transformers 5.5.0 × unsloth 2026.6.7 で
> gemma-2 推論が壊れる不具合に遭遇。Gemma 4 は最小 E2B でも 4bit 重みが 7GB 級で VRAM 6GB の学習が OOM 必至のため見送り。
> **最終的に `unsloth/gemma-3-1b-it`（4bit QLoRA）を採用**。本文中の「Gemma 2B」記述は gemma-3-1b に読み替え。
>
> **拡張履歴（2026-06-21）「先生対決」**: 教師データを 80→**1000件**に増量。さらに**教師を2種**用意し、
> 同一1000レースの状況で教師だけ差し替えて弟子Gemmaを2体作成 → 対決させる構成に発展。
> - `gemma-boat:1b`（**Gemini先生**, train_loss 1.41） / `gemma-boat-claude:1b`（**Claude先生**, train_loss 1.09）
> - ダッシュボードは **6者対戦**（Det / LLM / Gemini / 学習Gem(Gemini先生) / 学習Cla(Claude先生) / ユーザー）。

## 概要

### 何を作るのか（目的・背景）
ローカルPC（WSL2 + RTX A3000 6GB）で **Gemma 3 (1B) を QLoRA 微調整**し、ボートレース予想の
**「推論・説明」を強化**する。学習済みモデルを Ollama に取り込み、予測対戦ダッシュボードで
**Det / LLM / Gemini / 学習Gemma(Gemini先生) / 学習Gemma(Claude先生) / ユーザー** を並べて比較する。
さらに「**教えた先生（Gemini / Claude）の違いで弟子の予想がどう変わるか**」を見る先生対決を行う。

**目的（優先順）**:
1. **「AIを学習させる」とは何かを体験・理解する**（loss が下がる＝賢くなる、を実感）
2. **ボート特化の推論・説明の質を上げ、masaru 自身の予想眼もアップデートする**

**非目的**: 予測精度・ROI の向上。控除率25%の構造的天井（[[roi_structural_limit]]）は学習では超えられない。
ここは最初から「儲けではなく学び」と割り切る。

### 誰が使うのか
masaru 本人（学習教材）。

---

## 技術スタック
- **OS/環境**: WSL2（Ubuntu）+ CUDA on WSL（ドライバ 591.86 はWSL CUDA対応）
- **学習**: Unsloth（省VRAM QLoRA に最適化）/ 内部は transformers + PEFT + bitsandbytes
- **ベースモデル**: `unsloth/gemma-3-1b-it`（4bit、Hugging Face。当初予定の gemma-2-2b は前述の不具合で不採用）
- **手法**: 4bit QLoRA（6GB VRAM 制約に対応）
- **変換/推論**: LoRAをマージ→16bit→llama.cpp `convert_hf_to_gguf.py`(--outtype q8_0, ビルド不要) で GGUF 化
  → Windows Ollama に Modelfile で登録（`gemma-boat:1b`）
- **教師データ生成**: Gemini API（理由文の"先生役"、既存 `GEMINI_API_KEY` 流用）
- **比較UI**: 既存 `dashboard/src/Battle.jsx` に学習版Gemmaの予想列を追加

---

## 機能要件（必須機能）

### F1. 教師データ構築（最重要・学びの核）
過去レースの「状況 → 良い予想＋理由」を instruction 形式（JSONL）で **1000件** 用意する。素材:
- **過去レースの実データ**: 出走表・勝率・モーター・オッズ・天候 → 実際の結果（`past_data/`）
- **先生が理由文を生成**: 状況＋結果を渡し「結果が出る前の視点」での良質な解説＋買い目を作らせる。
- **教師2種（先生対決）**:
  - **Gemini先生**: `build_dataset.py` が Gemini API でお手本生成 → `train.jsonl`（1000件）
  - **Claude先生**: `dump_situations.py` で同一1000レースの状況+結果を抽出→バッチ化→
    Claude(サブエージェント)がお手本生成 → `train_claude.jsonl`（1000件）
  - 入力（レース集合）は完全に同一。教師（解説の書き手）だけ差し替え＝フェアな比較。

### F2. WSL2 学習環境の構築
- WSL2(Ubuntu) 導入 → CUDA on WSL 確認 → Python環境 + Unsloth + 依存
- Gemma 2B が VRAM 6GB でロード・1ステップ学習できることを最小確認

### F3. QLoRA 微調整
- 学習スクリプト（6GB向け設定: 4bit量子化・seq_len/batch小・gradient checkpointing）
- **loss の推移をログ表示**（学習が進む様子を可視化＝体験の山）
- LoRA アダプタのチェックポイント保存

### F4. 評価・変換
- 学習前後の比較（`eval_compare.py`）＋ **先生対決の2モデル比較**（`compare_teachers.py`、未学習レースで並べる）
- GGUF 変換 → Ollama に 2モデル登録: `gemma-boat:1b`(Gemini先生) / `gemma-boat-claude:1b`(Claude先生)
  （既存 `gemma2:2b`/`gemma4:e2b` は壊さず別名で並行追加）

### F5. ダッシュボードで6者対戦
- 予測パイプラインに**2つの学習版Gemma**の予想生成を追加（`predict_gemma_ft.py` の --model/--tag 切替、朝バッチで両方）
- 予測対戦ダッシュボードを **6者対戦**化: Det / LLM / Gemini / 学習Gem(Gemini先生) / 学習Cla(Claude先生) / ユーザー
  （一覧・詳細・戦績カード・月別的中率・収支推移・履歴表すべてに2モデルを反映）

---

## 非機能要件
- **VRAM 6GB 制約**: QLoRA 4bit 必須。OOM時は seq_len・batch・LoRA rank を段階的に下げる
- **既存環境を壊さない**: 現行 Ollama `gemma2:2b` と朝バッチはそのまま。学習版は別名で並行追加
- **再現性**: データ・ハイパーパラメータ・seed を記録
- **段階的・教材的に進める**: 各ステップで「今何をしているか・なぜか」を解説しながら進む（理解優先）
- **著作権・ToS配慮**: 第三者（プロ/X/予想サイト）の内容は私的学習目的に限定、再配布しない、出典を記録

---

## やらないこと（スコープ外）
- 予測精度・ROI の最適化（構造的天井のため目的にしない）
- フルファインチューニング（QLoRA のみ）／2Bより大きいモデル
- 商用利用、収集したサードパーティ内容の再配布・公開
- X(Twitter)/Web 収集が ToS・取得難易度で困難な場合は**潔くスキップ**（コアは既存ログ＋過去結果＋Gemini理由文で成立させる）

---

## ディレクトリ構成（予定）
```
gemma_finetune/
  spec.md / task.md
  environment.md            # WSL2/CUDA/Unsloth 構築手順メモ（再現用）
  data/
    build_dataset.py        # 教師データ構築(Gemini先生) → train.jsonl
    dump_situations.py      # 同一1000レースの状況+結果を抽出→claude_batches/ に分割(Claude先生用)
    train.jsonl             # Gemini先生 教師データ(1000)
    train_claude.jsonl      # Claude先生 教師データ(1000)
    claude_batches/         # Claude先生用バッチ入出力(batch_NN.json / out_NN.jsonl)
  compare_teachers.py       # 2モデル(Gemini先生/Claude先生)を同一レースで比較
  train_qlora.py            # QLoRA 学習（WSL2/Unsloth）※BASE=unsloth/gemma-3-1b-it
  eval_compare.py           # 学習前後の出力比較（1モデル+disable_adapter()でON/OFF）
  merge_export.py           # LoRA→16bitマージ（merged_16bit/ 生成）
  llama.cpp/                # 変換スクリプト用にclone（convert_hf_to_gguf.py を使用）
  ※WSL ~/gemma-ft/ に: lora_boat(現役), lora_boat_gemini, lora_boat_claude(各バックアップ)
  ※GGUF実体とModelfileはWindows側: C:\Users\HP\gemma-boat\（gemma-boat-q8_0 / gemma-boat-claude-q8_0）
predict_gemma_ft.py         # 学習版Gemmaで予想生成（--model/--out/--tag で2モデル切替）
generate_battle_data.py     # race_info/サマリに 2学習モデル(gemmaft/gemmaclaude)を取り込み
update_battle_dashboard.py  # 朝バッチ: 両学習モデルの予測を生成して公開
dashboard/src/Battle.jsx    # 6者対戦（学習Gem/学習Cla 列を追加）
```

---

## 外部連携
- **Hugging Face**: `unsloth/gemma-3-1b-it`（4bit）
- **Gemini API**: 理由文生成（既存 `credentials.env` の `GEMINI_API_KEY`）
- **Ollama**: 学習版モデル登録（`gemma-boat:1b`）
- **（任意）Web / X**: 競艇予想家情報の収集（ToS・著作権留意、best-effort）

---

## 備考・制約
- **6GB はギリギリ**: 2B QLoRA は通る見込みだが、OOM が出たら設定を絞る。Unsloth が最も省VRAM
- **WSL2 の GPU パススルー**が前提（CUDA on WSL）。最初の環境構築が最大の山
- **X(Twitter) 収集は現実的に困難**: 公式APIは有料/制限、スクレイピングはToS違反。取得できても少量・不安定。
  代替として競艇ニュース・コラム・公開データを検討。**無理なら本筋（既存ログ＋結果＋Gemini）で進める**
- **教師データの質がすべて**: Gemma の説明の良さは"お手本の理由文"の質で決まる。Gemini を先生にするのが現実的
- 2B は小型なので「劇的に賢くなる」より「ボートの語彙・着眼点が少し馴染む」程度を期待値とする
