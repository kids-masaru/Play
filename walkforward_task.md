# タスク管理: walk-forward backtest 基盤 + 自己改善ループ改修

## 最終更新: 2026-05-13

## 現在のステータス
- **Phase 2 (実装) 完了。**
- ベースライン確定 (短縮版WF: 直近6ヶ月acc + 45日Det ROI)
- 動作テスト Trial #1 完了 (ベースライン同等値で「主条件NG=改善せず」と正しく判定)
- 旧 results.tsv (post-leak-fix 17行) は results_pre_wf.tsv に退避済

## ベースライン値 (短縮版WF、wf_baseline.json)
- brier_1st: 0.596128, top1_acc: 55.75%, top3_acc: 86.26%
- roi.det (45日WF): ROI 100.51%, 1395 trades, monthly_win_rate 50%
- roi.llm (45日WF): ROI 63.08%, 1400 trades, monthly_win_rate 0%

## 次回やること
- 本番ループ運用開始: feature_candidates.md の優先度高10件から順に試行
- 各試行: `python auto_research/experiment_wf.py --note "変更内容"`
- 試行ごと約4分、採用条件を満たせば手動で git commit, 不採用なら revert

## 方針修正 (2026-05-12)
- past_odds_3t.csv が直近45日分しか無い問題が判明 → ハイブリッド方針 (Plan C) に変更
  - 2年WF: モデル精度評価 (Brier/log-loss/top-3 accuracy)
  - 45日WF: 実オッズROI評価 (Det/LLM相当)
- 自己改善ループ採用条件: 主=モデル精度改善 + 副=実運用ROI劣化なし (-10pt以内)

## タスク一覧

### Phase 2.1: walk-forward 評価器の実装
- [x] T1. `auto_research/walkforward_evaluator.py` 新規作成
  - [x] T1.1. 期間スライス関数 (週単位ロールフォワード生成)
  - [x] T1.2. 月初再学習ロジック (3モデル学習・保存)
  - [x] T1.3. 評価ロジック (realistic_evaluator.py のEV+Kelly再利用 / モデル精度評価追加)
  - [x] T1.4. Det/LLM 両モード対応
  - [x] T1.5. bootstrap 95%CI 計算 (週次ROI / メトリック値 resample 1000回)
- [x] T2. 45日WF ROI 動作確認: Det 100.51%, LLM相当 63.08% (5週)
- [x] T3. 2年accuracy WF 実行完了 (97週・88,568レース・9分): Brier 0.59, top3_acc 86.6%

### Phase 2.2: ベースライン取得 & Det/LLM 2年比較
- [x] T4. `auto_research/walkforward_baseline.py` 新規作成 (当初CSVベース→短縮版WF実行に改修)
- [x] T5. 45日WF Det/LLM 結果出力済 (paper trade と方向性整合: Det > LLM)
- [x] T6. paper trade 5週ぶん (Det 60% → WF Det 100%, LLM 1.5% → WF LLM 63%) → サンプル増で安定方向
- [x] T7. `wf_baseline.json` 確定 (短縮版WF: 直近6ヶ月accuracy + 45日Det ROI)

### Phase 2.3: 自己改善ループのスコア関数差し替え
- [x] T8. 既存ループ: `auto_research/experiment.py` (旧/composite_score) を特定
- [x] T9. 新規 `auto_research/experiment_wf.py` を作成 (短縮版WF: 直近6ヶ月acc + 45日Det ROI)
- [x] T10. コミット判定: 主条件(brier+top3_acc改善) AND 副条件(ROI劣化-10pt以内)
- [x] T11. 動作テスト完了: Trial #1 で4分・正常記録・期待通りREJECT

### Phase 2.4: 試行候補リスト整理
- [x] T12. `auto_research/feature_candidates.md` 新規作成
- [x] T13. リーク前提採用32件 + 過去catastrophic を分類
- [x] T14. 優先度別カテゴリ整理 (高10件 / 中10件 / 危険ゾーン)
- [x] T15. 20件以上を優先度順に整列

### Phase 2.5: ベースライン取り直し & ループ再開
- [x] T16. 既存 results.tsv → results_pre_wf.tsv にリネーム済
- [x] T17. experiment_wf.py --skip-rebuild 動作確認: Trial #1 で4分・正常記録
- [x] T18. 採用/不採用ロジック検証: ベースライン同等で「主条件NG」判定 (期待通り)
- [x] T19. ベースライン取り直し: walkforward_baseline.py を短縮版WF実行に改修
- 通常運用準備完了 (Det単独 paper trade と並行で運用可能)

## 作業ログ

### 2026-05-12
- 4/27〜5/11 LLM/Det paper trade 結果確認 → Det版本番一本化を実施 (morning_odds_runner.py 改修済み)
- 精度向上の方針議論 → walk-forward backtest 基盤構築 + 自己改善ループ改修方針確定
- planning スキルで spec/task 作成
- データ確認で過去オッズが直近45日分しか無いと判明 → ハイブリッド方針(C案)に変更
- Phase 2.1: walkforward_evaluator.py 作成、45日WF ROI 動作確認 (Det 100.51% / LLM 63.08%)
- Phase 2.2: 2年WF accuracy 実行 (97週・88,568レース・9分) → walkforward_baseline.py で baseline 確定
- Phase 2.3: experiment_wf.py 作成 (短縮版WFスコア + 主/副条件採用判定)
- Phase 2.4: feature_candidates.md 整理 (優先度高10/中10/危険ゾーン)
- Phase 2.5: results.tsv リネーム + 動作テスト完了
- 発見: ベースラインと試行のWFスコープ不整合 → walkforward_baseline.py を短縮版WFで取り直すよう改修
- masaru 確認事項:
  - WFウィンドウ: **週単位ロールフォワード**
  - 評価指標: **ROI + 月次勝率併用**
  - 修正範囲: **スコア関数 + 試行候補リストも事前整理**
  - スコープ: **WF基盤構築とループ修正まで一気に**
  - データ判明後: **ハイブリッド方針(C案)を採用**

### 2026-05-13
- task.md / spec.md の最新化 (実装結果反映)
- 実装結果の整理: 全Phase完了、運用開始可能

## 補足メモ
- 期待効果: 評価サンプル数 262 → 数万レース、CI 範囲が桁違いに狭くなる
- 自己改善ループ過去ログ (loop_log.txt) のスコア (+26.14, 903.42 等) はリーク前提なので参考程度
- 月1再学習で計算時間を抑える設計、フル2年で3時間以内が目標
- Det 単独運用 (5/12 開始) は本タスクと並行継続
