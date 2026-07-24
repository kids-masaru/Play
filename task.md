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

---

# 🔧 運用トラブル対応（2026-04-17〜2026-04-18）

## 最終更新: 2026-04-21 10:45

## 現在のステータス

**運用トラブル対応すべて完了。予測パイプラインの全層接続をコード検証＋実機シミュレーションで確認済み。models と build_features の不整合も手動 retrain で解消、健全な状態。**

### 予測対戦拡張（2026-07-24）
- [x] Grok API を予測対戦の任意参加者として追加（APIキー未設定時は他の処理を継続）
- [x] Grokの買い目・推論を対戦画面に表示
- [ ] `XAI_API_KEY` 設定後、初回の実API予測を実行して確認
- [ ] Gemini先生・Claude先生の新規1000件データで再学習（既存モデルは保持）
- [ ] Gemma 4 E2Bの最小QLoRAメモリテスト（6GB VRAM）
残課題はバリデーション窓シフト問題の検討のみ（急がず数日様子見）。

## 判明した真因（2026-04-18）

- GitHub Actions は全 green（壊れていなかった）
- `main_runner.py` の `push_to_github()` で `files_to_add` が `dashboard_data.json` と `loop_results.json` の2つだけ
- 実際には毎夜更新される `daily_odds_3t.csv` など他のCSVが add 対象外だった
- `dashboard_data.json` に差分がない日があると `git commit` が "nothing to commit" で失敗 → push もスキップ
- 結果として 2026-04-16 以降、夜バッチの更新が GitHub に反映されていなかった

## 次回やること（再開時の第一歩）

1. **04/22 以降の 3am ループ + 5am LINE通知が安定稼働するか見守り**（数日）
   - `auto_research/loop_log.txt` と LINE 着信を毎朝チェック
2. **バリデーション窓シフト問題の対処を判断**（下記「新規発覚」参照）
   - 案A: バリデーション期間を固定（evaluator.py か experiment.py 改修）
   - 案B: 実行開始時に無改造ベースラインを走らせて改善幅で評価
3. **（必要なら）別件で未コミットのファイルを整理**
   - `main_runner.py` + `utils/` — ことちゃんRAG連携（masaru さんの別作業）
   - `dashboard/package*.json` — Vite 8→7 ダウングレード（戻すか残すか要判断）

## 再開時のシステム現状（重要）

- **予測パイプラインの全層接続は検証済み（2026-04-21）**
  - 層1 データ → 層2 build_features → 層3 retrain/experiment → 層4 predict → LLM → LINE すべて接続
  - `past_data/ml_features.csv`（113,120行、187特徴量）と `models/lgb_model_*.txt` は完全一致状態
  - 実機シミュレーション: 大村 12R（04/20）で 1号艇 P=0.584 など合理的な確率が出力された
- **自動実行スケジュール**
  - 03:00 `BoatRaceAI_SelfImproveLoop` → `run_loop.bat` → claude 自己改善ループ
  - 05:00 `BoatRaceAI_NotifyResult` → `python notify_loop_result.py` → LINE サマリー通知（二重化保険）
  - 夜バッチ `run_daily.bat` → main_runner.py → 自動 commit & push
  - 朝バッチ `run_morning.bat` → morning_odds_runner.py → EV予測 & LINE
- **現在のベストスコア: 903.42**（exp #153、commit `6ef8d9a`）
- **但しバリデーション窓シフトにより現データでの評価は 212.39** → 同コードでも日によってスコアがブレる問題あり

## 新規発覚（2026-04-20 のループ結果より）

**バリデーション窓シフト問題**: 新レースデータが毎日DBに追加されることで評価の「最新30日窓」が前進し、同じコードでもスコアが日によって大きくブレる。例: 04/19 時点でのベスト 903.42 が、04/20 時点で同コード再実行すると 212.39。これはコード劣化ではなく評価データの入替による現象。loop の「ベスト超え」判定が成立しにくくなっている。

## 今回の調査で判明した事実（再発防止メモ）

### ① 3時のタスクが届かなかった一次原因
- `auto_research/run_loop.bat` の **`cd /d` が効いていなかった**
  - 原因: bat ファイルが UTF-8 保存 + 内部に日本語コメントがあり、cmd が parse を誤る
  - 修正済: `cd /d "%~dp0.."` に変更（bat自身の位置基準）

### ② LINE 通知が届かなかった二次原因
- `auto_research/notify_loop_result.py` の `print(msg)` が **絵文字（🤖📊等）を cp932 で出力できず UnicodeEncodeError で死亡**
- LINE送信は print の後に実行されるため到達できていなかった
- 修正済: `sys.stdout.reconfigure(encoding="utf-8")` と `safe_print()` ラッパーを追加

### ③ ダッシュボード結果ページが見れない真因
- **ローカル dist/ が 2026-03-29 で停止、GitHub Pages デプロイが 2026-03-19 で停止**
- Windows + Node v24 + rollup/rolldown ネイティブバイナリの組み合わせで `npm run build` が **exit 0xC0000409（STACK_BUFFER_OVERRUN）で無言クラッシュ**
  - Vite 8/7 どちらでも同じ、ソース最小化しても再現
  - **このマシンでのローカルビルドは事実上不可能**
- 正しい解決策は GitHub Actions（Ubuntu）でビルド → Pagesデプロイさせること
  - でも Actions が 3/19 から動いていない → 原因調査が次のステップ

### ④ ローカル閲覧の暫定手段
- `cd dashboard && npm run dev` でローカル dev サーバーは正常起動可能
- ブラウザで `http://localhost:5173/Play/` にアクセスすれば最新ソースで表示できる

## タスク一覧

- [x] A. `notify_loop_result.py` の UnicodeEncodeError 対策
- [x] B. 手動で LINE テスト送信（24試行サマリー）
- [-] C. ローカル dashboard rebuild（**Windows環境で実行不能と判明 → スキップ**）
- [x] D. `run_loop.bat` の堅牢化 ✅ 2026-04-18 完了
  - `pause` を削除、leading space を除去
  - `claude` と `notify_loop_result.py` の ERRORLEVEL を個別にログ
  - `cwd=%CD%` を開始ログに含めて cwd 問題の診断用情報を残す
  - `PYTHONIOENCODING=utf-8` 設定
- [x] E. **GitHub Pages 再デプロイ（最優先）** ✅ 2026-04-18 完了
  - 真因: Actions ではなくローカルpush不足だった
  - 1fa8fea で 04/18 の dashboard データを push → Actions が正常発火、27秒で green
- [x] 優先2. `main_runner.py` の `push_to_github()` 修正 ✅ 2026-04-18 完了（13b04ce）
  - `files_to_add` を8ファイルに拡張
  - `check=True` 外し、"nothing to commit" を吸収
  - push は commit 結果に関係なく必ず試行
- [x] 優先3. `run_morning.bat` にログ出力を追加 ✅ 2026-04-18 完了
  - stdout/stderr を `logs/morning.log` に追記、開始/終了タイムスタンプ + `ERRORLEVEL` を記録
  - `PYTHONIOENCODING=utf-8` 設定、`.gitignore` に `logs/` を追加
- [x] F. タスクスケジューラ設定見直し ✅ 2026-04-21 完了
  - `BoatRaceAI_SelfImproveLoop` を「ユーザーのログオン状態にかかわらず実行」に変更（masaru さん GUI 操作）
  - 04/21 3am で自動起動を確認、claude は正常完走
- [x] G. LINE通知の独立タスク化 ✅ 2026-04-21 完了（追加対応）
  - 04/21 3am 実行で `notify_loop_result.py` が run_loop.bat 内で発火せず LINE 未着
  - 手動で `python auto_research/notify_loop_result.py` を実行してサマリー送信成功
  - run_loop.bat の notify 呼び出しがタスクスケジューラ経由で不安定なため、独立タスク `BoatRaceAI_NotifyResult` を毎日 5:00 実行で新規作成
  - masaru さん GUI 作業で作成＋テスト成功
- [x] H. 予測パイプラインの全層接続検証 ✅ 2026-04-21 完了
  - Explore agent でコード上の接続をファイル名・行番号で検証（全 ✅ OK）
  - 実機シミュレーションで 1 レース分の予測を通し、確率が正常に出ることを確認
  - 軽微な不整合（`Venue_HighPayoutRate` の有無）を検出
- [x] I. models と build_features の不整合を解消 ✅ 2026-04-21 完了
  - `python retrain_model.py` を手動実行
  - モデル特徴量 188 → 187 に再学習、ml_features.csv と完全一致
  - 旧モデルは `*_backup.txt` に自動退避
  - 1着精度 73.06% / 2着精度 34.96% / 3着精度 27.94%

## 修正したファイル（未コミット分）

- `dashboard/package.json` + `dashboard/package-lock.json` — Vite 8.0.0 → 7.3.2、@vitejs/plugin-react 6 → 4 にダウングレード（ビルドクラッシュ調査の過程で変更、戻しても可）

## コミット済み（運用トラブル対応シリーズ）

- `1fa8fea` Auto-update dashboard data: 2026-04-18 11:30:00（daily_data 反映）
- `13b04ce` fix: 夜バッチのGitHub同期を複数ファイル対応＋commit失敗を吸収
- `bf36d71` fix: バッチスクリプトのログ出力とUTF-8対応を強化
- `724567f` feat: 自己改善ループに停止条件を追加（50試行/3時間/連続10回未更新）
- `37f5baa`〜`6ef8d9a` auto_research ループの自動改善（686.09 → 903.42）
- `32f2a39` chore: 自己改善ループの実験ログ追加と朝バッチ反映（2026-04-20）
- `cd0ae5a` docs: task.md を 2026-04-21 時点の運用トラブル対応完了状態に更新

## 作業ログ

### 2026-04-17
- 朝の LINE 通知が届かなかった件を調査開始
- タスクスケジューラ BoatRaceAI_SelfImproveLoop は 3:00:01 に起動していたが exit code 1 で失敗
- `loop_log.txt` が生成されていなかったため bat の初期段階で失敗と判明
- bat の日本語+UTF-8 問題を発見、`%~dp0..` 基準に修正
- 手動実行で claude ループが正常動作（24試行、3件コミット、ベスト 659.95 → 686.09）
- LINE通知が来ない原因を追跡 → `notify_loop_result.py` の print が UnicodeEncodeError で死亡と特定
- `safe_print` で修正、手動で LINE 送信成功（14:58）
- ダッシュボード問題: ローカル build が Windows ネイティブバイナリクラッシュで実行不能と判明
- 対応を GitHub Actions 経由に方針転換、ユーザーからの Actions スクショ待ちで中断

### 2026-04-18
- LINE試験メッセージの着信をユーザーが確認
- GitHub Actions スクショを受領 → **全 green、最新 Auto-update は 04/16 01:08 で停止**と判明
- 真因特定: `main_runner.py` の `push_to_github()` で `files_to_add` が2ファイルだけ → 差分なしで commit 失敗 → push スキップ
- 優先1実行: daily_data/ と dashboard/public/daily_data/ を手動 add → commit `1fa8fea` → push → Actions 27秒で green、ダッシュボード復旧
- 優先2実行: `main_runner.py` の `push_to_github()` を修正（add 対象を8ファイルに拡張＋commit失敗吸収＋push必須化）→ commit `13b04ce` push 済み
- 優先3実行: `run_morning.bat` にログ出力追加（`logs/morning.log`）、`PYTHONIOENCODING=utf-8` 設定、`.gitignore` に `logs/` 追加
- 優先4実行: `run_loop.bat` から `pause` 削除、leading space 除去、`claude`/`notify` の ERRORLEVEL を個別ログ、cwd を開始ログに含める

### 2026-04-19
- 朝の時点でループがまだ動いており、Max プラン契約確認 → 追加料金は発生しないが週次枠消費の懸念あり
- `program.md` に停止条件（50試行/3時間/連続10回未更新）を追加 → commit `724567f` push
- ループ中のコミット（`37f5baa`, `9ac41b1`, `0243367`, `6ef8d9a`）が実は未 push だったため、このとき一緒に origin に上がった（ベスト 903.42）
- ユーザーが手動でループ停止 → build_features.py の失敗実験残骸を revert、残りを commit `32f2a39` push

### 2026-04-20
- 3am 自動実行が新 program.md で走行 → **停止条件 #3 発動で正常終了**
- cwd も正しく記録された（昨日の run_loop.bat 改修が効いた証拠）
- バリデーション窓シフト問題が浮上（ベースライン 212.39、過去ベスト 903.42 との乖離）

### 2026-04-21
- 深夜にタスクスケジューラ「ログオン状態にかかわらず実行」設定変更 完了（masaru さん GUI 作業）
- 04/21 3:00 に自動起動、10試行（#188〜#197）で停止条件 #3 発動、03:41 終了
- しかし LINE が来ず → loop_log.txt に `loop end` / `notify done` のエントリが無い → run_loop.bat が notify に到達する前に途中終了している判明
- `notify_loop_result.py` を手動実行して今朝分のサマリーを LINE 送信成功
- 再発防止として独立タスク `BoatRaceAI_NotifyResult`（毎日 5:00）を作成、テスト実行で LINE 到達を確認
- これで run_loop.bat が途中死しても 5:00 に必ずサマリーが届く体制に
- ユーザーから「予測パイプラインが本当に繋がっているか」懸念 → 全層の接続をコード検証＋実機シミュレーションで確認（全 ✅）
- 検証中に models と build_features.py の軽微な不整合（Venue_HighPayoutRate）を発見 → `python retrain_model.py` 手動実行で解消
- 再学習結果: 1着 73.06% / 2着 34.96% / 3着 27.94%、backup 自動生成、ml_features 完全一致
