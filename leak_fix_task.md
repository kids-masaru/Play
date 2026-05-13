# タスク管理: build_features.py データリーク修正

## 最終更新: 2026-05-12

## 現在のステータス
- **全タスク完了 + paper trade 判定完了。Det版本番一本化済み。**

## 5/12 paper trade 結果 → Det版本番一本化
- 4/27〜5/11 (262レース): LLM ROI **1.57%** vs Det ROI **60.55%** (Det +59pt リード)
- Det 黒字は4/29単発依存だが、判定基準 ±20% を大きく超過のため Det 採用
- `morning_odds_runner.py:build_morning_notification` 改修: LINE通知はDet買い目主表示、Det空レースは通知から除外
- LLM推論は継続 (Stakesカラム記録継続) → monitoring 用 paper trade 続行

## 次回やること
- 5/13 朝バッチで新LINE通知フォーマットの動作確認（「本番:XXX円 N点」表記が出ればOK）
- Det単独運用での週次ROI監視（数週間連続赤字なら見直し）

## プランB結果（確率較正、Isotonic Regression）
- Brierスコア: 0.005-0.008 改善（理論通り）
- ROI効果: ほぼ無し（76.67%→76.72%、ノイズ範囲）
- 結論: 較正だけでは ROI 改善小、保留
- 較正器は `models/calibrators.pkl` に保存（将来本番組み込み余地あり）

## プランC結果（odds/probフィルタ）
- sweep結果: ROI 76% → **146%** に大幅改善（30日val期間）
- 採用フィルタ: `prob_min=0.01, ev_min=2.0, odds_max=500, top_n=4`
- val期間でチューニングしてるので overfitting リスクあり → 並走 paper trade で検証中
- 本番投入: morning_odds_runner.py に `Stakes_Det` カラム追加、LLM版と並列出力
- 比較ツール: `auto_research/compare_llm_vs_det.py`

## タスク一覧
- [x] T1. run_loop.bat の自動実行を無効化（2026-04-27 masaru が管理者PowerShellで `Disable-ScheduledTask -TaskName "BoatRaceAI_SelfImproveLoop"` 実行済み）
- [x] T2. results.tsv を results_legacy_pre_leak_fix.tsv に退避、ヘッダのみの新ファイル作成
- [x] T3. build_features.py 修正：方針(b) Python cumulative 実装
  - [x] T3.1〜3.3. _compute_leak_safe_player_stats() 関数で merge_asof + cumsum 実装
- [x] T4. ml_features.csv 再生成 + 所要時間記録（**84.2 秒**）
- [-] T5. 方針(a) はスキップ判断（方針(b)が十分高速）
- [x] T6. 方針(b)を採用
- [x] T7. 差分スポットチェック完了（2024-01-01: 0.18→0.0、2026-04-25: 0.176→0.176 ✓）
- [x] T8. verify_realistic.py 再実行 → ROI 642%→**76.6%** に低下（実運用 37% との差 39pt まで縮小）
- [x] T9. 3モデル再学習・上書き（OneDrive ReparsePoint 問題で OS temp 経由）
  - 1着予測 56.49% / 2着予測 29.28% / 3着予測 25.08% (test accuracy)
  - バックアップ: `models/lgb_model_*_pre_leak_fix.txt`
- [-] T10. before/after レポート作成中

## 作業ログ
### 2026-04-26
- 自己改善ループのスコアと実運用ROIの乖離（888% vs 37%）を調査
- 原因特定：build_features.py の集計SQLに日付フィルタ無し（時系列リーク）
- realistic_evaluator.py（本番準拠EV+Kelly評価器）を作成・実行 → ROI 642%でも乖離継続
- 真の原因が特徴量側のリークと判明
- planning スキルで本仕様書（leak_fix_spec.md / leak_fix_task.md）作成
- masaru の方針確定：
  - 実装方針: 両方試して速い方
  - モデル: リーク修正→再学習まで一気に
  - results.tsv: 別ファイルに退避
  - 3am自動ループ: 今夜から止める

## 補足メモ
- 旧 results.tsv（293件）の知見は `auto_research/notes.md` に既に記録済み。退避時は notes.md にも「ここまでリーク有り」追記が望ましい。
- VAL期間=最新30日 / 学習=それより前。リーク修正後は VAL も学習も両方クリーンな特徴量になる。
- 旧 evaluator (top3 100円) と 新 evaluator (EV+Kelly) どちらでROIが下がるかが見もの。新の方が prob を信じてEVに重み付けする分、リークの影響が大きく出ているはず → リーク除去で大きく下がるはず。
