# ボートレースAI 改善仕様書

## 概要

現在のシステムは「LightGBMで上位10レースを絞り込み → DeepSeek-R1で深い推論 → 買い目提案」というパイプラインで動作している。
本仕様書では、予測精度・収益性・運用性を段階的に向上させるための改善計画を定義する。

---

## Phase 1: オッズデータ取得 + 期待値フィルタ（高効果・低コスト）

### 背景・課題

- 現在、レース選抜は「LightGBMのエントロピーベース期待値スコア」のみで行っている
- **オッズ情報が一切使われていない** → 的中率が高くてもオッズが低ければ損、逆に的中率が低くてもオッズが高ければ利益が出る
- 真の「期待値」は `的中確率 × オッズ` であり、これがないと賭ける価値のあるレースを正しく選べない

### ゴール

1. boatrace.jp から3連単オッズを自動取得する
2. LightGBMの予測確率 × オッズ = **真の期待値（EV）** を算出する
3. EV > 1.0（回収率100%超の見込み）のレース・買い目のみをAI推論に回す
4. ダッシュボードとLINE通知にオッズ・EV情報を表示する

### 対象ファイルと変更内容

#### 1. `collect_race_data.py` — 新規関数追加

```
新規関数: scrape_odds_3t(jcd, rno, date_str)
```

- **URL**: `https://www.boatrace.jp/owpc/pc/race/odds3t?rno={rno}&jcd={jcd}&hd={date_str}`
- **取得データ**: 3連単 全120通りのオッズ（1-2-3, 1-2-4, ..., 6-5-4）
- **返却形式**: `[race_id, date, venue, rno, "1-2-3", odds_123, "1-2-4", odds_124, ...]`
  - または柔軟性を持たせて `[race_id, date, venue, rno, combination, odds]` の行ベースにする（120行/レース）
- **ヘッダー定義**: `ODDS_3T_HEADERS = ["ID", "Date", "Venue", "R", "Combination", "Odds"]`

**行ベース方式を採用する理由**:
- 1レース120通り × 最大144レース/日 = 最大17,280行だが、CSVとしては扱いやすいサイズ
- 買い目ごとのフィルタリング・結合がpandasで容易
- 将来的に2連単・2連複のオッズも同じ形式で追加可能

#### 2. `local_collect_race_data.py` — オッズ収集ジョブ追加

```
新規: Job 3 — 当日のオッズ取得（直前情報と同タイミング）
```

- 結果収集と同時刻（18時以降）に、**当日の確定オッズ**を取得
- 翌日予測用には**前日22時時点のオッズ**（前夜オッズ）も取得を検討
  - ただし、翌日の番組が出た直後はオッズが安定しないため、予測フェーズ直前（23時頃）に取得するのが最適
- 保存先: `daily_data/daily_odds_3t.csv`

**タイミング整理**:
```
18:00頃 実行:
  Job 1: 翌日の出走表 → daily_raw_race_data.csv
  Job 1.5: 選手コース別成績 → daily_player_course_stats.csv
  Job 2: 当日の結果 → daily_history_results.csv
  Job 2: 当日の直前情報 → daily_raw_beforeinfo.csv
  Job 3 (NEW): 当日の確定オッズ → daily_odds_3t.csv（反省会・ROI計算用）
```

**2回バッチ方式（アプローチB）を採用**:

```
[夜間バッチ 23時] main_runner.py（既存）
  Job 1: 翌日の出走表取得
  Job 1.5: 選手コース別成績取得
  Job 2: 当日の結果・直前情報取得
  Job 3 (NEW): 当日の確定オッズ取得（反省会・ROI計算用）

[朝バッチ 9時] morning_odds_runner.py（新規）
  Job A: 当日（=翌日分）の前売りオッズ取得
  Job B: LightGBM確率 × 実オッズ → EV計算
  Job C: EV > 1.0 の買い目のみで予測やり直し → daily_predictions.csv 更新
  Job D: LINE通知（本日のEVベース推奨買い目を送信）
```

**メリット**:
- 朝9時の前売りオッズは比較的安定しており、実オッズに近い
- 実オッズでEV計算ができるため、「買い目の価値判断」が飛躍的に向上
- 夜間バッチは既存の予測（LightGBM確率のみ）を維持、朝バッチでEV強化版に上書き

#### 3. `local_ai_pipeline.py` — EV計算とフィルタリング

```
変更: run_predictions() 内のレース選抜ロジック
```

**夜間バッチ（既存パイプラインの改善）**:
- AIプロンプトに「オッズ意識」を注入:
  - expert_knowledge.jsonに「EV最大化」の具体的な判断基準を追加
- LightGBM確率ベースの仮予測を生成（従来通り）

**朝バッチ（morning_odds_runner.py — 新規）**:
- 当日の前売りオッズを取得
- LightGBM確率 × 実オッズ → 真のEVを算出
- `EV = Σ(predicted_prob[combo] × odds[combo])` で各買い目のEVを計算
- EV > 1.0 の買い目のみを「推奨候補」としてAIに提示
- EV強化版の予測で daily_predictions.csv を更新
- LINE通知を送信

#### 4. `generate_dashboard_data.py` — オッズ連携強化

```
変更: calculate_roi() の収益計算ロジック
```

- 現在: Payoutを結果CSVから取得（3連単の払戻金額のみ）
- 改善: オッズCSVを参照し、各買い目の事前オッズも記録
- ダッシュボードJSONに追加するフィールド:
  ```json
  {
    "recent_races": [{
      "pre_odds": 45.2,        // 事前オッズ (NEW)
      "expected_value": 1.35,   // 事前EV (NEW)
      "ev_category": "高EV"     // "高EV" / "中EV" / "低EV" (NEW)
    }]
  }
  ```

#### 5. `main_runner.py` — LINE通知へのEV情報追加

- 推奨買い目の表示に「推定EV」を追加:
  ```
  📍 住之江7R: 1-3-2 (EV: 1.85) ← NEW
  ```

#### 6. `expert_knowledge.json` — EV関連ルール追加

```json
{
  "expert_patterns": [
    {
      "pattern_id": "ev_threshold",
      "condition": "EV > 1.0",
      "insight": "期待値が1.0を超える買い目のみが長期的にプラス収支をもたらす",
      "advice": "EV < 0.8 の買い目は推奨リストから除外すること"
    },
    {
      "pattern_id": "odds_value_zone",
      "condition": "Odds 15x-80x and AI confidence > 60%",
      "insight": "中穴ゾーン（15〜80倍）はAI的中時のリターンが最大化される",
      "advice": "本命（〜5倍）は回収率が低く、万舟（100倍+）は的中率が低い。中穴ゾーンを優先"
    }
  ]
}
```

#### 7. 新規ファイル: `daily_data/daily_odds_3t.csv`

```
ID,Date,Venue,R,Combination,Odds
20260327_住之江_7,2026-03-27,住之江,7,1-2-3,12.5
20260327_住之江_7,2026-03-27,住之江,7,1-2-4,45.2
...
```

---

## Phase 2: 2着・3着予測 → 3連単対応（高効果・中コスト）

### 背景・課題

- 現在のLightGBMは「1着予測」のみ（multiclass 6クラス）
- 3連単は1-2-3着の順番の組み合わせ（120通り）を当てる必要がある
- 1着しか予測できないと、2-3着の選定がAI（LLM）の曖昧な推論に依存してしまう

### ゴール

- LightGBMで2着・3着の予測モデルも構築する
- 1着×2着×3着の確率を掛け合わせて、各3連単組み合わせの的中確率を推定する
- 推定確率 × オッズ = EV で買い目を自動ランク付けする

### 対象ファイルと変更内容

#### 1. `build_features.py`

- Target列の追加: `Target_2nd`, `Target_3rd`（結果データから2着・3着の艇番を抽出）
- 既存の `Target_1st` に加えて出力

#### 2. `retrain_model.py`

- モデルを3つ訓練:
  - `lgb_model_1st.txt` — 1着予測（既存）
  - `lgb_model_2nd.txt` — 2着予測（新規）
  - `lgb_model_3rd.txt` — 3着予測（新規）
- 各モデルで独立にA/Bテスト
- パラメータは共通でOK（同じ特徴量セット）

#### 3. `local_ai_pipeline.py`

- 3モデルの確率を組み合わせて3連単確率を推定:
  ```
  P(i-j-k) ≈ P_1st(i) × P_2nd(j|i≠j) × P_3rd(k|i≠k,j≠k)
  ```
  ※ 条件付き確率の近似として、各着順の確率を正規化して使用
- 上位N通りの組み合わせをAIプロンプトに提示

---

## Phase 3: 教訓の条件別分類（中効果・低コスト）

### 背景・課題

- 現在の反省（`daily_reflections.csv`）は「RaceID, Date, Lesson」のみ
- 全レースの教訓が混在しており、特定条件のレースに関連する教訓を選別できない
- 例: 江戸川の荒天レースの教訓が、平和島の晴天レースの予測に注入される

### ゴール

- 教訓に「条件タグ」を付与して保存する
- 予測時に、対象レースの条件に合致する教訓のみを注入する

### 対象ファイルと変更内容

#### 1. `daily_reflections.csv` — カラム追加

```
RaceID, Date, Venue, Weather, WindLevel, Lesson
```
- `Venue`: 会場名
- `Weather`: 天候（晴/曇/雨/雪）
- `WindLevel`: 風速レベル（calm/moderate/strong）

#### 2. `local_ai_pipeline.py`

- 反省フェーズ: 教訓保存時に会場・天候情報を付与
- 予測フェーズ: `get_recent_lessons()` を条件フィルタ付きに改修
  - 同じ会場の教訓を優先
  - 似た天候条件の教訓を優先
  - フィルタ後の上位5件を注入

---

## Phase 4: SQLite移行 + モーター特徴量（中効果・中コスト）

### 背景・課題

- CSVファイルが肥大化（past_data/ で70MB超）
- 重複排除・条件検索のたびに全ファイルをメモリに読み込んでいる
- モーター番号は特徴量にあるが、モーター自体の成績（2連率等）は未活用

### ゴール

- CSVベースのデータストアをSQLiteに移行
- モーターの直近成績を特徴量に追加

### 対象ファイルと変更内容

#### 1. 新規: `database.py` — DB層

- SQLiteデータベース: `data/boatrace.db`
- テーブル: `races`, `results`, `beforeinfo`, `odds`, `predictions`, `reflections`, `player_stats`, `motor_stats`
- CRUD関数を提供
- 既存CSVからの一括マイグレーションスクリプト付き

#### 2. `build_features.py`

- モーター2連率の特徴量追加:
  - `B{n}_MotorWinRate` — そのモーターの直近勝率
  - `B{n}_Motor2inRate` — そのモーターの直近2連率
- モーター成績はboatrace.jpの各レース場のモーター成績表から取得可能

#### 3. 全スクリプト

- `pd.read_csv()` → `sqlite3` クエリに置き換え
- `append_to_csv()` → `INSERT INTO` に置き換え

---

## Phase 5: ダッシュボードUI改善（低効果・低コスト）

### ゴール

- 場所別・レース番号別の勝率グラフ
- AIの推奨理由サマリー表示
- EV分布チャート
- モバイル最適化（LINEから直接確認しやすいレイアウト）

### 対象

- `dashboard/src/App.jsx`
- `generate_dashboard_data.py`（集計項目追加）

---

## 非対象（現状維持）

- **AI推論エンジン**: DeepSeek-R1:14b をそのまま使用（ユーザー指示）
- **ベッティング金額**: 1レース3000円の固定投資（Phase 1完了後にケリー基準を検討）
