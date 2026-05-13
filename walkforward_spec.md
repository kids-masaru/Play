# walk-forward backtest 基盤構築 + 自己改善ループ改修

## 概要

### 目的・背景
- 現状の自己改善ループは「最新30日val期間」でスコア評価しており、val期間がデータ更新で前進すると同じモデルでもスコアが大きく揺れる (903.42→212.39 などの記録あり、loop_log.txt)。
- 4/27〜5/11 paper trade (262レース) では LLM ROI 1.57% vs Det ROI 60.55% で Det 採用判断は出たが、的中数は両方とも1回ずつで統計的にはノイズ範囲。サンプル過少で本物の差か運か判別困難。
- DB には過去約2年分のレース結果 (113,912行) があり、build_features.py のリーク修正済みで「過去レース時点で未来データを漏らさない特徴量」が作れる状態に。これを walk-forward backtest として全期間で評価できれば、評価サンプルが100倍以上に増え、Det/LLM 比較も自己改善ループのスコア判定も「本物の改善か運か」を統計的に判別可能になる。

### 利用者
- masaru (個人開発・自己改善ループ運用者)

## 技術スタック
- Python 3.x / pandas / SQLite (data/boatrace.db)
- LightGBM (既存3モデル)
- 既存モジュール再利用: `build_features.py`, `realistic_evaluator.py`, `local_ai_pipeline.py`

## 機能要件（必須機能）

### データ前提と方針修正 (2026-05-12)
- `past_data/ml_features.csv` は 2024-01-01〜2026-05-10 (約2年・113,912レース) で 2年WF可能
- `past_data/past_odds_3t.csv` は **2026-03-28〜2026-05-11 (約45日)** しかない (Boatrace公式は過去オッズ非公開)
- → **ハイブリッド方針** に変更:
  - **2年WF**: モデル精度 (Brier / log-loss / top3 accuracy) 評価。オッズ不要
  - **45日WF**: 実オッズROI評価 (EV+Kelly with Det フィルタ)
- 自己改善ループは「2年WFモデル精度改善 AND 45日WFのROIが劣化しない」を採用条件に

### 1. walk-forward 評価器 (`auto_research/walkforward_evaluator.py`)
**(A) 2年WF モデル精度評価**
- 期間: ml_features.csv 全体 (2024-01-01〜)、評価開始は学習用に最低6ヶ月確保した後 (2024-07以降)
- ウィンドウ:
  - 学習データ: 各評価週の開始日より前の全期間 (expanding window)
  - 評価期間: 翌1週間 (約100週分の評価ブロック)
  - モデル再学習: **月初に1回**再学習し、その月の4週分は同じモデルで評価
- 指標 (3モデル分):
  - **Brier score** (multi-class、確率と実結果の二乗誤差)
  - **log-loss** (cross-entropy)
  - **top-1 accuracy** (1着的中率)、**top-3 accuracy** (1〜3着のいずれかが当たる率)
- 出力: 週次・月次の指標 CSV (`auto_research/wf_model_results.csv`)

**(B) 45日WF 実オッズROI評価**
- 期間: 過去オッズの存在する範囲 (2026-03-28〜)、評価開始は最低2週間学習データ確保後 (実質4週ブロック)
- ウィンドウ:
  - 学習データ: 評価週開始日より前の全期間 (expanding window、2024-01-01〜評価週前日)
  - 評価期間: 翌1週間
  - モデル再学習: 週ごとに1回 (期間が短いため月単位より週単位の方が現実的)
- 評価ロジック: `realistic_evaluator.simulate_realistic_buys` + `evaluate_buys` を再利用
- モード:
  - **Det**: ev_thr=2.0, prob_min=0.01, odds_max=500
  - **LLM相当 (deterministic)**: ev_thr=1.0, prob_min/odds_max なし
- 出力: 週次・累積 ROI CSV (`auto_research/wf_roi_results.csv`)

**(C) 共通**
- bootstrap 95%CI (resample 1000回、週単位ブロック)
- 月次集計と「ベースライン超え月数 / 全月数」の算出

### 2. ベースライン取得 (`auto_research/walkforward_baseline.py`)
- experiment_wf.py と同じ**短縮版WF** (直近6ヶ月accuracy + 45日Det ROI) を実行
- 試行とスコープを揃えるため必須 (フル2年WFと短縮版で値が微妙にズレるため)
- 出力: `auto_research/wf_baseline.json` (モデル精度ベースライン + ROIベースライン + CI)
- 自己改善ループのコミット判定基準として参照される

### 3. 自己改善ループのスコア関数差し替え (`auto_research/experiment_wf.py` 新規)
- 既存 `experiment.py` (composite_score+30日val) は残し、新規 `experiment_wf.py` を作成
- **短縮版WFを採用** (直近6ヶ月 accuracy + 全45日 Det ROI、1試行 約4分)
- フル2年WFは別途 `walkforward_evaluator.py --mode both` で手動実行可能

### 4. コミット判定の強化 (実装版)
- 改修後の採用条件 (AND 結合):
  - **主条件 (モデル精度)**: brier_1st が改善 (低下) **かつ** top3_acc が改善
  - **副条件 (実運用ROI 劣化チェック)**: 45日WF Det ROI がベースラインから **−10pt 以内** (大幅劣化なし)
- 上記を満たさない試行は採用しない (revert)
- 補足: モデル精度改善が ROI 改善を保証しないため、副条件で「実運用ROIを大きく壊さない」を担保する
- 統計的有意性 (bootstrap CI 比較) は将来の強化候補としてスコープ外に

### 5. 試行候補リストの事前整理 (`auto_research/feature_candidates.md`)
- 過去 `results_legacy_pre_leak_fix.tsv` (293件) を分類:
  - 試し済みかつリーク前提で「効いた」とされたもの → 再評価候補 (上位)
  - 試し済みで効かなかったもの → 除外
  - まだ試してないアイデア (新規候補)
- カテゴリ別 (会場系・コース系・モーター系・気象系・派生計算系) に整理
- 自己改善ループは優先度順にこのリストから試行を取り出す方式に

### 6. Det/LLM の2年ROI 比較レポート
- WF 評価器を使って Det/LLM の全期間ROI と月次推移を出力
- 4/27〜5/11 の paper trade 結果と整合性確認
- 月次推移グラフ (CSV → 後でダッシュボード組込み余地)

## 非機能要件

- **計算時間**: フル WF 評価 (Det/LLM 同時) で **2〜3時間以内** が目標。これを超える場合はモデル再学習頻度を月1から2ヶ月に1回に下げる等の調整
- **再現性**: random_state 固定、bootstrap も seed 固定
- **互換性**: 既存の `realistic_evaluator.py` のロジック (EV+Kelly) はそのまま再利用、配列インターフェースのみ統一

## やらないこと（スコープ外）
- 自己改善ループの 1試行=1特徴量追加 という基本枠組みは変更しない (試行候補リスト整理は範囲内、ループのロジック大改造は別タスク)
- LightGBM ハイパーパラメータの自動チューニング (別タスク)
- 強化学習・オンライン学習などの大幅アーキ変更
- ダッシュボード UI への WF 結果の組み込み (CSV出力までで止める、UI 改修は別タスク)
- Det 単独運用そのものは継続。本タスクと並行運用

## ディレクトリ構成（変更箇所）

```
Play/
├─ auto_research/
│  ├─ walkforward_evaluator.py       # ★新規 (Phase 2.1) (A)モデル精度+(B)ROI 両対応
│  ├─ walkforward_baseline.py        # ★新規 (Phase 2.2、短縮版WF実行)
│  ├─ experiment_wf.py               # ★新規 (Phase 2.3、自己改善ループ1試行)
│  ├─ wf_model_results.csv           # ★新規 (出力: 2年WFモデル精度)
│  ├─ wf_roi_results.csv             # ★新規 (出力: 45日WF ROI)
│  ├─ wf_baseline.json               # ★新規 (出力: ベースライン値+CI)
│  ├─ wf_summary.json                # ★新規 (出力: walkforward_evaluator 実行サマリ)
│  ├─ feature_candidates.md          # ★新規 (Phase 2.4)
│  ├─ experiment.py                  # 既存 (旧/composite_score、参照のみ)
│  ├─ evaluator.py                   # 既存 (旧スコアロジック、参照のみ)
│  ├─ realistic_evaluator.py         # 既存 (45日WF評価に流用)
│  ├─ results.tsv                    # ★新フォーマット (WF版1行〜)
│  ├─ results_pre_wf.tsv             # ★退避 (post-leak-fix 17行)
│  └─ notes.md                       # 既存 (試行結果記録継続)
├─ walkforward_spec.md / walkforward_task.md   # 本ドキュメント
```

## 外部連携
- なし (DB + CSV + ローカルモデルのみ)

## 備考・制約
- expanding window 採用理由: sliding (固定期間) よりデータ活用効率が高く、過去2年程度なら concept drift も小さいと判断
- 月1再学習採用理由: 週ごとに3モデル学習すると 100週 × 30秒 = 50分超え、月1なら 24回 × 30秒 = 12分で済む
- 月次勝率の集計単位は「カレンダー月」(例: 2024-01, 2024-02, ...)、評価期間に部分月が出る場合は最初と最後を含む
- bootstrap は週次ROIをresample単位とする (週がブロック)

## 検証ステップ（受け入れ基準）と実装結果

1. ✅ `walkforward_evaluator.py` 完走、CSV 出力済 (`wf_model_results.csv` 97行 / `wf_roi_results.csv` 10行)
2. ✅ 2年WFモデル精度: brier_1st=0.5961, top3_acc=86.63% (97週・88,568レース)
3. ✅ 45日WF実ROI: Det 100.51% > LLM相当 63.08% (paper trade と方向性整合)
4. ✅ ベースライン JSON 生成済 (短縮版WFで取り直し、experiment_wf.py と同スコープ)
5. ✅ 自己改善ループ Trial #1 動作確認: ベースライン同等値で REJECT 判定 (期待通り)
6. ✅ `feature_candidates.md` 整理完了 (優先度高10 + 中10 + 危険10)
7. ✅ 1試行 約4分 (短縮版WF採用により大幅高速化)

## 実装結果サマリ (2026-05-13)

### ベースライン値 (wf_baseline.json)
- accuracy (短縮版・直近6ヶ月): brier_1st=0.596128, top1_acc=55.75%, top3_acc=86.26%
- roi.det (45日WF): ROI **100.51%**, 1395 trades, monthly_win_rate 50%
- roi.llm (45日WF): ROI 63.08%, 1400 trades, monthly_win_rate 0%

### 重要な発見
- 週次再学習で Det ROI が paper trade の **60.55% → 100.51%** に上昇
- 「最新データで再学習し続けるとROIが上がる」ことを示唆 (将来の改善余地)

### 運用開始準備完了
- 本番ループ: `python auto_research/experiment_wf.py --note "変更内容"`
- 採用判定が成立すれば手動 `git commit`、不採用なら `git checkout build_features.py`
