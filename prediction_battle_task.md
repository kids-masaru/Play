# 予測対戦ダッシュボード task

## Phase 1: MVP

### A. 朝バッチ側の追加データ出力
- [ ] A-1. `morning_odds_runner.py` に「daily_race_info.json 生成」関数追加
  - 各艇の基本情報 (級別・勝率・当地勝率・ST・モーター・体重・展示タイム・当地レーン勝率)
  - 気象・水面情報
  - オッズ表 (上位20)
  - 出力先: `dashboard/public/daily_data/daily_race_info.json`
- [ ] A-2. `morning_odds_runner.py` に「feature_importance Top5 出力」追加
  - 各レースの LightGBM feature_importance(importance_type="gain") から Top5 抽出
  - 出力先: `dashboard/public/daily_data/daily_feature_importance.json`
- [ ] A-3. 朝バッチ実行で正常に2つのJSONが生成されることを確認

### B. ダッシュボード フロント実装
- [ ] B-1. 既存 App.jsx に 'battle' ページを追加 (page state に追加)
  - ナビゲーションタブ追加
- [ ] B-2. レース一覧コンポーネント
  - daily_race_info.json と daily_predictions.csv (AI予測) を結合
  - 会場×R の一覧、各レースに AI予測トップ買い目を表示
  - クリックで詳細展開 or 詳細ページへ
- [ ] B-3. レース詳細コンポーネント
  - 各艇テーブル (主要情報)
  - オッズ表
  - AI予測 (上位5買い目)
  - **AI重要特徴量 Top5 表示** ★
- [ ] B-4. 予測入力フォーム
  - 買い目テキスト入力
  - 自信度スライダー
  - メモ
  - localStorage 保存
  - 「保存しました」フィードバック
- [ ] B-5. 対戦履歴コンポーネント
  - localStorage の予測 × daily_history_results.csv を突き合わせ
  - 直近30件を表形式
- [ ] B-6. 精度比較サマリコンポーネント
  - 月別 的中率棒グラフ (AI vs 自分)
  - 累積 ROI 折れ線
  - 自信度別 的中率

### C. レスポンシブ対応
- [ ] C-1. CSS の media query で スマホ表示調整
  - レース一覧: スマホで縦並び
  - 詳細テーブル: 横スクロール
  - グラフ: 高さ抑える

### D. ドキュメント
- [x] D-1. spec.md 作成
- [x] D-2. task.md 作成
- [ ] D-3. README 風に「ダッシュボードの使い方」を簡単に記載

## Phase 2 (将来)

- [ ] クラウド同期 (Firebase 検討)
- [ ] スマホ→PC データ同期
- [ ] 結果突き合わせのバッチ自動化
- [ ] 「あなたが勝ったパターン」の傾向分析
- [ ] レース直前のオッズ自動更新

## Phase 1.5 (3者比較拡張)

- [x] HistorySummary を Det vs LLM vs ユーザー の3者並列に拡張
- [x] generate_battle_data.py で ai_predictions_summary.json (全期間) を出力
- [x] Battle.jsx で AI予測サマリを fetch して的中率計算

## Phase 1.6 (Gemini API追加で4者比較)

- [x] credentials.env に GEMINI_API_KEY 設定 (ユーザー作業)
- [x] generate_gemini_predictions.py - 当日のレース予測を Gemini 2.5 Flash で生成
- [x] run_gemini_predictions.bat - env load + python実行
- [x] generate_battle_data.py で Gemini予測 (stakes/見解/思考) を含める
- [x] Battle.jsx を 4者対応 (Det/LLM/Gemini/ユーザー)
- [x] 朝バッチへの Gemini予測統合 (2026-06-11 `update_battle_dashboard.py` を run_morning.bat に組込み・9:00自動)

## Phase 2.0 (傾向タブ・偏り分析) 2026-06-21

- [x] 偏り集計: Detの3連単買い目 × 実結果で会場別/レース番号別の的中率・ROIを集計 (`analysis/boat_bias_analysis.py`)
  - 結果: 対象346レース/的中11(3.2%)/ROI72%。母数が薄く「得意ゾーン」はほぼノイズと判明（鳴門・12Rの肌感は3連単では不成立）
- [x] 指標切替: 母数の大きい **1号艇1着率(イン率)** で再集計 (`analysis/boat_venue_tendency.py`、全17,580レース)
  - 会場偏り本物(徳山62.9%↔戸田39.8%)、レース番号偏り本物(2R46%→12R72%)、ただし「当たる≠儲かる」
  - 発見: Det本命1着率53.5%≒イン率54.8%＝モデルはほぼ1号艇買いで上積み乏しい（[[roi_structural_limit]] に追記）
- [x] ダッシュボード「傾向」タブ追加 (`dashboard/src/Tendency.jsx` + App.jsx タブ、`boat_tendency.json` を fetch)
  - 会場別/レース番号別イン率のヒートマップ（緑=堅い/赤=荒れる）、Det本命1着率・中央払戻も表示
- [x] 朝バッチ自動化: `update_battle_dashboard.py` に集計実行を追加＋`boat_tendency.json` を公開対象に。毎朝9:00更新
- [ ] (将来) イン堅め戦略の第7予測者（後半R×堅い会場で1号艇本命）。ただしROIは控除率の壁で100%困難の見込み

## 履歴

- 2026-06-07: spec / task 初版作成
- 2026-06-07: Phase 1.5 (3者比較) + 1.6 (Gemini追加で4者比較) 完了
- 2026-06-21: Phase 2.0 傾向タブ・偏り分析 完了（イン率ヒートマップ＋朝バッチ自動化）
