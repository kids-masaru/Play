# ボートレースAI 改善タスク一覧

> 詳細仕様は `spec.md` を参照

---

## Phase 1: オッズデータ取得 + 期待値フィルタ

### 1-1. オッズスクレイピング関数の実装 ✅
- [x] `collect_race_data.py` に `scrape_odds_3t(jcd, rno, date_str)` を追加
  - boatrace.jp の3連単オッズページをパースする
  - 120通りの組み合わせ → `[race_id, date, venue, rno, combination, odds]` 形式で返却
  - `ODDS_3T_HEADERS` 定数を定義
- [x] 手動テスト: 特定の日付・会場・レースでオッズが正しく取得できることを確認
  - daily_data/daily_odds_3t.csv に18,000行超のデータが実際に取得済み（本番動作で確認）

### 1-2. 夜間バッチへのオッズ収集統合 ✅
- [x] `local_collect_race_data.py` に Job 3（当日確定オッズ収集）を追加
  - 結果取得と同タイミング（18時以降の夜間バッチ）
  - `daily_data/daily_odds_3t.csv` に保存
  - レジューム対応（既に取得済みの会場はスキップ）
- [x] `main_runner.py` は変更不要（`local_collect_race_data.main()` 内で実行されるため）

### 1-3. 朝バッチスクリプト morning_odds_runner.py を新規作成 ✅
- [x] `morning_odds_runner.py` を新規作成
  - Job A: 当日レースの前売りオッズを取得 → `daily_data/daily_odds_3t.csv` に追記
  - Job B: LightGBM確率 × 実オッズ → EV算出
  - Job C: EV > 1.0 の買い目のみでAI予測を実行 → `daily_predictions.csv` 更新
  - Job D: LINE通知（EVベース推奨買い目を送信）
- [x] タスクスケジューラに朝9時のバッチを登録する手順をREADMEに記載（README.md参照）

### 1-4. AI予測パイプラインへのEV統合 ✅
- [x] `local_ai_pipeline.py` に仮想EV推定（LightGBM確率ベース簡易3連単候補）を追加
- [x] 夜間バッチのプロンプトに有力3連単候補（確率順）を注入

### 1-5. ROI計算へのオッズ統合 ✅
- [x] `generate_dashboard_data.py` の `calculate_roi()` を改修
  - `daily_odds_3t.csv` から事前オッズを参照
  - `recent_races` に `pre_odds` と `ev_category` フィールドを追加
- [x] ダッシュボードJSON出力の拡張

### 1-6. AI予測プロンプトの改善 ✅
- [x] `expert_knowledge.json` にEV関連ルールを追加
  - `ev_threshold` パターン
  - `odds_value_zone` パターン
  - `ev_weighted_selection` パターン
- [x] `local_ai_pipeline.py` のプロンプトに「オッズ意識」を組み込み

### 1-7. LINE通知の拡張 ✅
- [x] `main_runner.py` の通知テンプレートにEV情報を追加
  - 推奨買い目の横にEV値を表示（朝バッチ適用後）
  - 朝9時EV強化版の案内を追加

### 1-8. retrain_model.py のデータマージ対応 ✅
- [x] `retrain_model.py` の Step 1 に `daily_odds_3t.csv` → `past_data/past_odds_3t.csv` のマージを追加

---

## Phase 2: 2着・3着予測 → 3連単確率推定

### 2-1. 学習データの拡張 ✅
- [x] `build_features.py` に `Target_2nd`, `Target_3rd` の抽出ロジックを追加
  - 結果データ `Result` 列（例: "1-3-5"）から2着・3着を分離
  - `extract_2nd_place()`, `extract_3rd_place()` を実装
- [x] `ml_features.csv` の出力カラムに追加

### 2-2. 2着・3着モデルの訓練 ✅
- [x] `retrain_model.py` を拡張して3モデル訓練に対応
  - `lgb_model_1st.txt` — 1着予測（既存）
  - `lgb_model_2nd.txt` — 2着予測（新規）
  - `lgb_model_3rd.txt` — 3着予測（新規）
  - `train_single_model()`, `evaluate_old_single_model()` に共通化
  - `_update_model_if_better()` ヘルパー追加
- [x] 各モデルのA/Bテストを独立実行

### 2-3. 3連単確率の推定ロジック ✅
- [x] `local_ai_pipeline.py` に3連単確率推定関数を追加
  - `estimate_trifecta_probs(probs_1st, probs_2nd, probs_3rd)` → 上位N通りの確率
  - 条件付き確率の近似: `P(i-j-k) ≈ P_1st(i) × P_2nd(j|i≠j) × P_3rd(k|i≠k,j≠k)` を正規化
  - `predict_with_model()` 共通関数を追加
  - `load_lgb_model_2nd()`, `load_lgb_model_3rd()` を追加
- [x] AIプロンプトに上位確率の組み合わせを提示（3モデル統合版）
  - 2着/3着モデル未整備時は1着モデルのみの簡易版にフォールバック

### 2-4. EVとの統合（Phase 1完了後） ✅
- [x] `morning_odds_runner.py` で3モデル統合確率 × 実オッズ = 真のEVを算出
  - `estimate_trifecta_probs()` を利用した高精度EV算出
  - 2着/3着モデル未整備時は従来の1着モデルのみの簡易確率にフォールバック
- [x] EV > 1.0 の買い目のみを推奨リストに含める

---

## Phase 3: 教訓の条件別分類

### 3-1. 反省データの拡張 ✅
- [x] `daily_reflections.csv` に `Venue`, `Weather`, `WindLevel` カラムを追加
  - 既存データとの後方互換: カラムが存在しなければ自動追加
- [x] `local_ai_pipeline.py` の `run_reflection()` で教訓保存時に条件情報を付与
  - `daily_raw_beforeinfo.csv` から天候・風速データを取得して紐付け
  - `classify_wind_level()` で風速を3段階に分類（calm/moderate/strong）
  - 反省プロンプトにも天候・風情報を追加（より具体的な教訓を引き出す）

### 3-2. 条件フィルタ付き教訓注入 ✅
- [x] `get_relevant_lessons(venue, weather, wind_level)` を新規追加
  - 同会場の教訓: +3点
  - 似た天候の教訓: +2点
  - 似た風レベルの教訓: +1点
  - スコア順 → 日付新しい順でソートし上位5件を返却
- [x] `run_predictions()` の教訓注入をレースごとの条件付き取得に変更
- [x] `morning_odds_runner.py` の教訓注入も条件フィルタ付きに変更
- [x] 旧 `get_recent_lessons()` は後方互換のため維持

---

## Phase 4: SQLite移行 + モーター特徴量

### 4-1. データベース層の構築 ✅
- [x] `database.py` を新規作成
  - SQLiteスキーマ定義（8テーブル: races, results, beforeinfo, odds, player_stats, predictions, reflections, motor_stats）
  - インデックス定義（Date, RaceID等のキーカラム）
  - WALモード + NORMAL同期で読み書き性能最適化
  - テーブル別CRUD関数（insert_races, get_races_by_date 等）
  - `query_df()` — SQLクエリ → DataFrame 変換
  - `migrate_csv_to_db()` — 既存CSV一括マイグレーション
  - `python database.py` でスタンドアロン実行可能
- [x] 既存CSVデータとの互換: CSV書き込み維持 + DB同時書き込み（デュアルライト方式）

### 4-2. 全スクリプトのDB対応 ✅
- [x] `local_collect_race_data.py` — Job 4（モーター成績取得）追加 + `_sync_csv_to_db()` で全daily CSVをDB同期
- [x] `local_ai_pipeline.py` — 予測・反省保存時にDB同時書き込み
- [x] `retrain_model.py` — daily→past マージ時にDB同時INSERT
- [x] `generate_dashboard_data.py` — `import database` 追加（将来のDB読み込み対応準備）
- [x] `build_features.py` — DB優先読み込み、CSVフォールバック付き

### 4-3. モーター特徴量の追加 ✅
- [x] `collect_race_data.py` に `scrape_motor_stats(jcd, date_str)` を実装
  - URL: `https://www.boatrace.jp/owpc/pc/race/motorlist?jcd={jcd}&hd={date_str}`
  - 各モーターの勝率・2連率・3連率を取得
  - `MOTOR_STATS_HEADERS` 定数を追加
- [x] `local_collect_race_data.py` に Job 4（モーター成績収集）を追加
  - 翌日開催会場のモーター成績をDB直接保存
  - 最新日付チェックでスキップ対応
- [x] `build_features.py` に `B{n}_MotorWinRate`, `B{n}_Motor2inRate` を追加
  - DB内のmotor_statsテーブルから会場×モーター番号でマッチング
  - モーターデータ未整備時は0埋め（既存動作に影響なし）

---

## Phase 5: ダッシュボードUI改善

### 5-1. 集計データの拡張 ✅
- [x] `generate_dashboard_data.py` に場所別(`venue_stats`)・レース番号別(`race_stats`)の集計を追加
- [x] EV分布データ(`ev_stats`)の追加
- [x] AI推奨理由の抽出(`parse_reasoning()`)を追加
- [x] Payout安全化（文字列/空値ガード、ゼロ除算ガード）

### 5-2. フロントエンド改善 ✅
- [x] `dashboard/src/App.jsx` に場所別勝率チャート（Venue Hit Rate）を追加
- [x] EV分布チャート（EV Distribution ROI）を追加
- [x] レース番号別分析チャート（Race Number Analysis: Hit Rate + ROI 二軸）を追加
- [x] AI推奨理由サマリー表示（トグル開閉式）
- [x] モバイルレスポンシブ対応（768px + 480px ブレイクポイント）

---

## 実施順序

```
Phase 1（オッズ+EV）   ✅ 完了
  ↓
Phase 2（2着3着予測）   ✅ 完了
  ↓
Phase 3（教訓分類）     ✅ 完了
  ↓
Phase 4（SQLite移行）   ✅ 完了
  ↓
Phase 5（UI改善）       ✅ 完了
```

## 備考

- DeepSeek-R1:14b → Gemma4:e2b に移行済み（2026-04-16）
- 各Phase完了時にダッシュボードでROI変化を確認し、効果測定を行う
- Phase間で依存関係があるもの（例: Phase 2-4はPhase 1のオッズデータに依存）は前Phaseの完了を待つ

---

## Phase 6: コアモデルの根本的修正

> 詳細仕様は `spec.md` の「Phase 6」を参照

### 背景

コードレビュー（2026-04-16）で判明した3つの根本問題に対処する。
問題: ①データリーク（ランダム分割）、②クラス不均衡未対応、③3連単確率の正規化バグ

### 6-1. 時系列分割への変更（最優先）

- [ ] `retrain_model.py` の `train_single_model()` を時系列分割に変更
  - `train_test_split()` を削除
  - `time_series_split(df, feature_cols, target_col, val_days=60)` を実装
  - Dateカラムを `_get_feature_and_target()` 内で保持するよう変更
  - A/Bテストも同じ時系列分割で評価
- [ ] 変更後の精度数値を記録（ベースライン比較用）

### 6-2. クラス不均衡補正

- [ ] `retrain_model.py` の LightGBM params に `is_unbalance: True` を追加
- [ ] 変更前後で2〜6号艇の的中率を比較記録

### 6-3. 条件付き確率の正規化修正

- [ ] `local_ai_pipeline.py` の `estimate_trifecta_probs()` に正規化処理を追加
  - 各条件付き確率が「除外インデックスを除く合計=1」になるよう正規化
  - `_normalize_excluding(probs, exclude_indices)` ヘルパーを実装
- [ ] 同じ修正を `auto_research/experiment.py` の `estimate_trifecta_probs()` にも適用

---

## Phase 7: 特徴量エンジニアリングの強化

> 詳細仕様は `spec.md` の「Phase 7」を参照

**※ 組み合わせや閾値の最適化は `auto_research/` の自己改善ループが自動実施。**
**人手では「新しいデータソース接続」と「基盤コード整備」のみ行う。**

### 7-1. 選手の短期調子指標（直近勝率）

- [ ] `build_features.py` に短期勝率の計算ロジックを追加
  - `past_race_data.csv` + `past_history_results.csv` を Date ソートして結合
  - 各選手・各レースの時点で「直近30日の1着率」「直近7日の1着率」を算出
  - カラム名: `B{n}_WinRate_30d`, `B{n}_WinRate_7d`, `B{n}_Top3Rate_30d`
  - 注意: **当日以降のデータを参照しないこと**（未来リーク禁止）

### 7-2. 選手×会場の相性

- [ ] `build_features.py` に選手×会場別成績を追加
  - 過去データから「選手ID × 会場」の通算1着率を算出
  - カラム名: `B{n}_VenueWinRate`
  - 最低出走数（例: 5走以上）を条件に設定。不足時はリーグ平均で補完

### 7-3. 展示タイムの変化量

- [ ] `build_features.py` に展示タイム変化量を追加
  - 直近3走の平均展示タイムとの差分を特徴量化
  - カラム名: `B{n}_ExTime_Delta`
  - 同会場・同コースの直近値を使用するのが理想（データ量に依存）

### 7-4. モーターの使用期間

- [ ] `build_features.py` にモーター使用開始からの累計出走数を追加
  - `past_race_data.csv` から モーター番号 × 会場 で出走数を集計
  - カラム名: `B{n}_MotorAge_Races`

---

## Phase 8: LLMプロンプトの最適化

> 詳細仕様は `spec.md` の「Phase 8」を参照

### 8-1. Temperature変更（即実施可能・低リスク）

- [ ] `local_ai_pipeline.py` の `call_deepseek()` の temperature を `0.7 → 0.3` に変更
- [ ] `morning_odds_runner.py` の Ollama 呼び出し箇所も同様に変更
- [ ] 変更後1週間の予測傾向を確認（特定組み合わせへの偏りが減るか）

### 8-2. Chain-of-Thoughtプロンプトの追加

- [ ] `local_ai_pipeline.py` の予測プロンプトを5ステップの推論形式に変更
  - ステップ1: 1号艇の支配力評価
  - ステップ2: 最大脅威艇の特定
  - ステップ3: 気象・外乱要因の評価
  - ステップ4: 教訓の適用
  - ステップ5: EV上位から最終推奨決定
- [ ] `morning_odds_runner.py` も同様のステップ形式に変更

### 8-3. 教訓活用プロンプトの改善

- [ ] 教訓注入部分のプロンプトを「今回のレースへの関連理由を明示させる」形式に変更
  - 両ファイル（`local_ai_pipeline.py`, `morning_odds_runner.py`）が対象

---

## 実施順序（推奨）

```
Phase 6-1（時系列分割）      ← 最優先。精度評価の信頼性を確立
  ↓
Phase 6-2（クラス不均衡）    ← 6-1と同時着手可能
  ↓
Phase 6-3（確率正規化）      ← 6-1と同時着手可能
  ↓
Phase 8-1（Temperature）    ← 軽微なので6と並行実施可能
  ↓
Phase 7（特徴量強化）        ← 自己改善ループで並行進行
  ↓
Phase 8-2/8-3（CoT）        ← Phase 6完了後に効果測定してから実施
```

## 現在のステータス（2026-04-16）

- Phase 1〜5: ✅ 完了
- Gemma4:e2b への LLM 切り替え: ✅ 完了
- auto_research 自己改善ループ構築: ✅ 完了（ベースライン: ROI 659.95%）
- Phase 6〜8: 📋 計画策定完了・実施待ち
