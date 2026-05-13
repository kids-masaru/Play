# build_features.py データリーク修正

## 概要

### 目的・背景
- 自己改善ループ(`auto_research`)が「特徴量を追加するほどスコア向上」と報告しているが、実運用ROIは37%(累計-90,010円)。
- 調査の結果、`build_features.py` の集計SQLに **日付フィルタが無く**、各レース時点で **未来のレース結果まで含めた集計値** を特徴量に入れていることが判明（時系列リーク）。
- これにより backtest ROI が嘘（旧 evaluator 207%, 新 EV+Kelly evaluator 642%）になり、本番運用の37%と大幅乖離している。
- 本番DBは「今日まで」しかデータが無いので未来リークしないが、backtest時のDBは「val期間の未来=最新まで」入っているため両者に整合性が無い → backtestの全結果が信頼不可能。

### 利用者
- masaru（個人開発・自己改善ループ運用者）

## 技術スタック
- Python 3.x / pandas / SQLite (data/boatrace.db)
- LightGBM（既存モデル群）

## 機能要件（必須機能）

### 1. リーク修正対象（4つの集計）
`build_features.py` 内、以下4つの集計を「そのレース日 **より前** のデータのみ」で算出するよう改修：

| L | 関数/カラム | 現状SQL概要 |
|---|---|---|
| 115-122 | `VenueWinRate`, `VenueRaceCount` | races + results JOIN, GROUP BY PlayerID,Venue（日付フィルタ無し） |
| 142-149 | `VenueLanePWinRate`, `VenueLanePRaceCount` | races + results JOIN, GROUP BY PlayerID,Venue,Lane（日付フィルタ無し） |
| 168-177 | `Career2inRate`, `Career3inRate` | races + results JOIN, GROUP BY PlayerID（日付フィルタ無し） |

### 2. 実装方針（両方試して速い方を採用）
- **方針(b) Python cumulative**：`results` を (PlayerID, Date) でソート、累積カウントで O(N)
- **方針(a) DB側 correlated JOIN**：SQL に `WHERE res.Date < r.Date` を追加
- 113,912行 × 4集計を計算 → 速い方を採用。両方試して結果を残す。

### 3. 再生成と検証
- 修正後 `build_features.main()` で `past_data/ml_features.csv` 再生成
- `python auto_research/verify_realistic.py` 再実行
- 新評価器のROIが「30〜80%程度」のレンジに落ちれば成功（実運用37%との整合性）

### 4. 本番モデル再学習
- リーク修正後の `ml_features.csv` を使って `models/lgb_model_1st.txt` `lgb_model_2nd.txt` `lgb_model_3rd.txt` を再学習・上書き
- 既存ファイルは `*_pre_leak_fix.txt` にバックアップ

### 5. 過去スコアの退避
- `auto_research/results.tsv` (293件) を `auto_research/results_legacy_pre_leak_fix.tsv` にリネーム退避
- 新規 `results.tsv` をヘッダのみで作成 → ベースライン取り直し可能に

### 6. 3am自動ループ停止
- 本日(2026-04-26)夜から `run_loop.bat` を停止（タスクスケジューラ無効化 or .bat 退避）
- リーク修正＆再学習＆ベースライン確認が終わったら再開判断

## 非機能要件

- **再生成時間**: 5分以内目標（現状の build_features.main 所要時間 + α）
- **互換性**: `build_features.main()` のシグネチャ・出力形式は維持。`local_ai_pipeline.py` 等 import 側に影響を与えない
- **検証可能性**: 修正前後で同一レースの特徴量を比較し、未来レース結果が混入していないことをスポットチェック

## やらないこと（スコープ外）

- 確率較正(Isotonic Regression等)：リーク修正だけで効果見てから判断（プランB）
- 実運用パイプラインのLLM部分検証：別タスク
- フィルタチューニング(odds上限、prob下限)：プランCで検討
- リーク修正以外の特徴量追加・削除：本タスクは「リーク除去」のみに集中

## ディレクトリ構成（変更箇所）

```
Play/
├─ build_features.py                     # ★修正
├─ past_data/
│  └─ ml_features.csv                    # ★再生成
├─ models/
│  ├─ lgb_model_1st.txt                  # ★再学習
│  ├─ lgb_model_2nd.txt                  # ★再学習
│  ├─ lgb_model_3rd.txt                  # ★再学習
│  ├─ lgb_model_1st_backup.txt           # 既存(放置)
│  ├─ lgb_model_*_pre_leak_fix.txt       # ★新規バックアップ
├─ auto_research/
│  ├─ results.tsv                        # ★ヘッダのみにリセット
│  ├─ results_legacy_pre_leak_fix.tsv    # ★退避
│  ├─ realistic_evaluator.py             # 既存(本タスクで利用)
│  ├─ verify_realistic.py                # 既存(本タスクで利用)
└─ leak_fix_spec.md / leak_fix_task.md   # 本ドキュメント
```

## 外部連携
- なし（DB+CSV+ローカルモデルのみ）

## 備考・制約

- `Date < r.Date` か `<= r.Date` か：**strict less than (`<`)** を採用。同じ日のレース結果も含めない（同日レースを未来扱い）。
- 113k行のうち、初期レース（DB最初期=2024-01-01）はキャリア集計値が 0 になる。これは正しい挙動（過去データが無いため）。`fillna(0)` の既存挙動を維持。
- リーク修正後はモデル精度が下がる可能性大（リークで盛られていたため）。実運用ROIに近い方向に動くことを期待。

## 検証ステップ（受け入れ基準）

1. `build_features.main()` が修正後も無事完走し、`ml_features.csv` 形状が同じ（113,912行 × 221列、列順同一）
2. リーク修正前後で同じレース行を比較し、`Career2inRate` 等が変化（特に最初期レース）していること
3. `verify_realistic.py` の新評価器ROIが **642% → 100%以下** に下がる
4. 旧評価器(top3 100円固定)のROIも **207% → より低い値** に下がる
5. 本番モデル再学習後、`run_daily.bat` 系がエラー無く動く（特徴量列が揃っているため自動成立を期待）
6. `run_loop.bat` のタスクスケジューラが無効化されていること
