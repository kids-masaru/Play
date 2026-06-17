# Gemma ローカル微調整 — タスク管理

## 最終更新: 2026-06-17

## 現在のステータス
- Phase 1（planning）: **承認済み（2026-06-17）**
- Phase 2（実装）: **T1〜T3 完了（学習環境 構築済み）**。次は Phase 2-B（教師データ）→ T8/T9（学習体験）
- 方針確定: WSL2ローカル一本 / ゴール=学習前後を予測対戦で比較(フル) /
  教師データ=既存ログ＋過去結果＋Gemini理由文（＋任意でWeb/X）

## 次回やること
- **T4-T5（小規模データ）→ T8/T9（初回の学習体験）**: まず少量データでQLoRAを1回まわし、
  lossが下がる＝学習が進むのを体感する。そこから本データに広げる。
- WSL実行は `~/gemma-ft/venv/bin/python`。作業は ~/gemma-ft 配下。

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
- [ ] T8. `train_qlora.py`: QLoRA設定（4bit・seq_len/batch小・grad checkpoint）
- [ ] T9. **超小規模で1回転**（数十件で loss 低下＆受け答え変化を確認）= 体験チェックポイント
- [ ] T10. 本データで微調整、loss推移・チェックポイント保存

### Phase 2-D: 評価・変換・ダッシュボード比較
- [ ] T11. `eval_compare.py`: 学習前後で同一レースの出力を並べて比較
- [ ] T12. `export_gguf.sh` + `Modelfile`: GGUF変換 → Ollama登録（`gemma-boat:2b`、既存は温存）
- [ ] T13. `predict_gemma_ft.py`: 学習版Gemmaで予想生成（既存pipeline流用）
- [ ] T14. 予測対戦ダッシュボードに「学習版Gemma」を追加し、学習前/後/Det/Gemini/ユーザーを比較
- [ ] T15. 振り返り（masaru の学び・気づきを整理、必要なら2周目の方針）

## 作業ログ
### 2026-06-17
- planning 起動。AskUserQuestion で方針確定:
  - 環境=WSL2ローカル一本 / ゴール=学習前後を予測対戦で比較(フル) /
    教師データ=既存Gemma・Geminiログ＋過去レース状況・結果＋(可能ならWeb/Xの予想家情報)
- PCスペック確認: RTX A3000 Laptop VRAM **6GB** / RAM 32GB / i7-11850H → 2B QLoRA はローカルで可能
- spec.md・task.md 作成 → 承認待ち
