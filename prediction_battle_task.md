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

## 履歴

- 2026-06-07: spec / task 初版作成
