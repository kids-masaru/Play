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

- DeepSeek-R1:14b は現状維持（変更なし）
- 各Phase完了時にダッシュボードでROI変化を確認し、効果測定を行う
- Phase間で依存関係があるもの（例: Phase 2-4はPhase 1のオッズデータに依存）は前Phaseの完了を待つ
