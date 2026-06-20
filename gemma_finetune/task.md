# Gemma ローカル微調整 — タスク管理

## 最終更新: 2026-06-21

## 現在のステータス
- Phase 1（planning）: **承認済み（2026-06-17）**
- Phase 2（実装）: **T1〜T14 完了**。学習→比較→GGUF→Ollama→ダッシュボード参戦まで一通り達成。
- **2026-06-21 大幅拡張「先生対決」**: 教師データ 80→**1000件**に増量し再学習。さらに
  **教師2種**を用意し弟子Gemmaを2つ作成して対決させる構成に:
  - `gemma-boat:1b`（**Gemini先生**・1000件, train_loss 1.41）
  - `gemma-boat-claude:1b`（**Claude先生**・1000件, train_loss 1.09）※Claudeがサブエージェントでお手本生成
  - 同一1000レースの状況で教師だけ差し替え＝フェアな先生比較。
  - ダッシュボードは **6者対戦**（Det/LLM/Gemini/学習Gem(Gemini先生)/学習Cla(Claude先生)/あなた）。
  - 関連: `dump_situations.py`(状況抽出), `compare_teachers.py`(2モデル比較),
    `predict_gemma_ft.py`(--model/--out/--tagでモデル切替), train_claude.jsonl(1000)。
- 方針確定: WSL2ローカル一本 / ゴール=学習前後を予測対戦で比較(フル) /
  教師データ=既存ログ＋過去結果＋Gemini理由文（＋任意でWeb/X）
- **モデル確定: `unsloth/gemma-3-1b-it`（4bit QLoRA）**。
  Gemma4は最小E2Bでも4bit重みが7GB級→VRAM 6GBで学習OOM必至＝見送り（2026-06-18 実測）。

## 次回やること
- **T13（既存pipelineから `gemma-boat:1b` を Ollama API で呼ぶ予想生成）→ T14（ダッシュボードに「学習版Gemma」枠を追加）**
- WSL実行は `~/gemma-ft/venv/bin/python`。作業は ~/gemma-ft 配下。
- 学習コマンド: `~/gemma-ft/venv/bin/python ~/gemma-ft/train_qlora.py --epochs 3`（約6.5分・80件）
- 推論: Windows Ollama `gemma-boat:1b`（既存 `gemma2:2b` と並行・温存）

## タスク一覧

### Phase 2-A: 学習環境の構築（最初の山）
- [x] T1. WSL2(Ubuntu 22.04) 導入済みを確認（VERSION 2）。新規導入は不要だった
- [x] T2. CUDA on WSL OK（WSL内 nvidia-smi 成功＝RTX A3000 6GB 認識）。Python3.10.12/gcc11.4あり、pip/conda無し
- [x] T3. Python環境 + Unsloth + 依存インストール、Gemma 2B ロード確認 **完了**
      ※ sudo不要の方法: get-pip.py(--user) → virtualenv → ~/gemma-ft/venv → pip install unsloth
      導入: torch 2.10.0+cu128, unsloth 2026.6.7, bitsandbytes 0.49.2, transformers 5.5.0, peft 0.19.1, trl 0.24.0, xformers 0.0.35
      検証: torch CUDA有効・GPU(RTX A3000)認識OK / `unsloth/gemma-2-2b-it-bnb-4bit` を4bitロード成功(VRAM 2.26GB、6GB中3.7GB余裕)
      実行コマンド: WSL `~/gemma-ft/venv/bin/python`。テストscript: ~/gemma-ft/check_gpu.py, load_test.py

### Phase 2-B: 教師データ構築（学びの核）
- [x] T4. 素材の棚卸し: past_data/ に出走表(past_race_data)・オッズ(past_odds_3t_backfill 507日分)・
      直前情報(past_raw_beforeinfo)・結果(past_history_results 128,509件) が揃うと確認。ID で結合可
- [-] T5. `gemma_finetune/data/build_dataset.py` 作成・検証済み（状況組み立て・オッズ照合198/200 OK）。
      **次: masaru が `run_build_dataset.bat 80` を実行**（Gemini API ~80回でお手本生成 → train.jsonl）
- [ ] T6. (任意/best-effort) `collect_web_tips.py`: Web/X の競艇予想家情報収集（後回し可）
- [ ] T7. train/val 分割・整形・件数とサンプル品質チェック（train.jsonl 生成後）

### Phase 2-C: 微調整（体験の山）
- [x] T8. `train_qlora.py` 作成（QLoRA・SFTConfig・train_on_responses_only・gemma-3テンプレ）。学習ループ動作OK
- [x] T9. **解決済み（2026-06-18）**: モデルを Gemma2 → `gemma-3-1b-it` に変更してバグ回避。
      旧バグ: transformers 5.5.0 + unsloth 2026.6.7 で gemma-2-2b の推論が壊れる（loss~20・生成崩壊）。
      Gemma4検討: 最小E2Bでも4bit重み7GB級→VRAM6GBで学習OOM必至のため見送り。
      **結果**: gemma-3-1b で 80件・3ep 学習成功（約6.5分）。train_loss 平均2.14・終盤~1.5＝健全域。
      生成サンプルも自然な日本語の競艇分析（お手本の「推論」スタイルを習得）。OOMなし。
- [-] T10. 80件データで微調整・LoRA保存まで実施済み（`~/gemma-ft/lora_boat`）。
      本データ拡張（件数増）は評価(T11)で物足りなければ実施。

### Phase 2-D: 評価・変換・ダッシュボード比較
- [x] T11. `eval_compare.py` 完成・実行（2026-06-19）。1モデル+disable_adapter()でON/OFF比較。
      結果: **形式・文体の学習は成功**（学習前=買い目すら出せず冗長／学習後=[推論]→[買い目]形式で3連単を出す）。
      ただし**予想の中身は浅い**（軸選びが教師と逆/矛盾するケースあり）＝1b+80件では妥当。学びの核を達成。
- [x] T12. **完了（2026-06-19）**: LoRAをマージ→16bit→GGUF(q8_0, 1.0GB)→Windows Ollama登録。
      手順: cmake無いためunsloth自動変換は使わず、`merge_export.py`(merged_16bit)→
      llama.cppの`convert_hf_to_gguf.py --outtype q8_0`(ビルド不要)→`ollama create gemma-boat:1b`。
      GGUF: C:\Users\HP\gemma-boat\gemma-boat-q8_0.gguf / Modelfile同梱。テンプレ gemma3-instruct 自動検出。
      動作確認: サンプルレースで [推論]→[買い目] を生成。**モデル名は実体に合わせ `gemma-boat:1b`**（2bでなく1b）。
- [x] T13. **完了（2026-06-19）**: `predict_gemma_ft.py`。Ollama `gemma-boat:1b` を /api/generate で呼び、
      学習時と同じ instruction で当日レースを予測 → `daily_gemma_predictions.csv`（**追記式=履歴蓄積**）。
      今日19レース生成OK（傾向: 1-2-3 など本命寄りが多い＝1bらしい）。
- [x] T14. **完了（2026-06-19）**: 予測対戦ダッシュボードに「学習版Gemma」(ピンク#ec4899)を5者目として追加。
      `generate_battle_data.py`がrace_info(ai_picks_gemmaft)とサマリ(stakes_gemmaft)に取り込み、
      `Battle.jsx`を5者対戦化(一覧/詳細/戦績カード/月別的中率/収支推移/履歴表)。esbuild構文OK。
      `update_battle_dashboard.py`の朝バッチに`predict_gemma_ft.py`を組み込み(--skip-gemma対応)。
      **副次の重要修正**: Gemini予測が毎日上書きで履歴に残らないバグ(履歴でGeminiが常に"-")を、
      `generate_gemini_predictions.py`を追記式upsertに変更して解消。学習版Gemmaも同方式で最初から永続化。
- [ ] T15. 振り返り（masaru の学び・気づきを整理、必要なら2周目の方針）
- [ ] (デプロイ) push→GitHub Actionsビルド後に実機(ダッシュボード)で5者表示を確認

## 作業ログ
### 2026-06-18
- T9 リベンジ（前回の判断待ちを解消）。masaru 方針: 「Gemma3でOK、可能ならGemma4」
- Gemma4 実測検証: 最小 `gemma-4-E2B-it` 4bit でもDLキャッシュ7GB級・マルチモーダルで
  VRAM 6GB の学習はOOM必至 → 見送り。 DL自体も回線不安定で長時間ハング。
- → masaru 選択で **gemma-3-1b** に確定。80件・3ep 学習成功（train_loss 平均2.14・終盤~1.5）。
  生成も自然な競艇分析。**Gemma2バグ完全解消**。LoRA保存: ~/gemma-ft/lora_boat
- 次: T11（学習前/後の出力比較）→ T12（GGUF→Ollama）→ T14（ダッシュボードに学習版Gemma追加）

### 2026-06-17
- planning 起動。AskUserQuestion で方針確定:
  - 環境=WSL2ローカル一本 / ゴール=学習前後を予測対戦で比較(フル) /
    教師データ=既存Gemma・Geminiログ＋過去レース状況・結果＋(可能ならWeb/Xの予想家情報)
- PCスペック確認: RTX A3000 Laptop VRAM **6GB** / RAM 32GB / i7-11850H → 2B QLoRA はローカルで可能
- spec.md・task.md 作成 → 承認待ち
