# 予測対戦ダッシュボード spec

> **実装拡張（2026-06-21）「傾向（攻略図）」タブ追加**:
> - 母数の大きい指標（**1号艇1着率=イン率**、全17,580レース）で会場別・レース番号別の偏りをヒートマップ可視化。
>   3連単(346レース/的中11)では母数が薄くノイズだったため指標を切替えた（[[roi_structural_limit]] と整合）。
> - 発見: **Det本命1着率53.5% ≒ 全体イン率54.8%** → モデルは「ほぼ1号艇買い」でイン率以上の上積みが乏しい。
>   レース番号偏りは本物(2R 46%→12R 72%)だが「当たる≠儲かる」（オッズに織込み済み）。
> - 集計: `analysis/boat_venue_tendency.py` → `dashboard/public/daily_data/boat_tendency.json`、`dashboard/src/Tendency.jsx` で表示。
>   朝バッチ `update_battle_dashboard.py` に組込み済みで毎朝9:00自動更新。

## 目的

ユーザー (masaru) がボートレースの予測眼を養うため、AI予測 + 判断材料を見ながら自分の予測を入力・蓄積し、AI vs 自分の精度を比較できる仕組みを作る。儲ける目的ではなく**学習**目的。

## 背景

- これまでの実験で「AI予測+EVフィルタ」は ROI 90%が天井。儲かるレベル(100%超え)には届かない。
- 一方、ここまでの基盤(daily_predictions.csv, ml_features.csv 224特徴量, 朝バッチ毎日稼働)は良いものができている。
- これを **「ユーザーの学習教材」** として活用する。

## ユーザー回答(2026-06-07)

| 確認事項 | 回答 |
|---|---|
| 使う環境 | **スマホでも見たい** |
| 予測タイミング | **AI予測を見てから入力** (AIを参考に学ぶ) |
| 判断材料の詳細度 | **詳細** (シンプル項目 + AIが重要視した特徴量Top5) |

## 全体構成

```
[既存]                          [新規追加]
朝バッチ (morning_odds_runner.py)
  ├─ daily_predictions.csv     ├─ daily_race_info.json (各艇の判断材料)
  └─ daily_odds_3t.csv         └─ daily_feature_importance.json (Top5)
              ↓
       dashboard (React + Vite)
       既存 'dashboard', 'ailab' ページ
              + 新規 'battle' ページ ★

[ユーザー予測]
ブラウザ localStorage (Phase 1)
  └→ CSV エクスポート可能
       将来: Firebase等のクラウド同期 (Phase 2)
```

## 画面設計

### 'battle' ページ - 4セクション構成

#### 1. 今日のレース一覧
- 開催全レース (会場×R) を一覧
- 各レースに「AI予測トップ買い目 + 確率 + 期待値」を併記
- 「予想入力」ボタンで詳細ページへ

#### 2. 各レース詳細表示
- **基本情報**: 会場、R、レース時刻、気象、水面、波高
- **各艇テーブル (1〜6号艇)**:
  - 級別、勝率、当地勝率、平均ST、モーター2連率
  - 体重、Tilt、展示タイム
  - **当地×コースの相性 (VenueLanePWinRate)**
- **オッズ表**: 3連単上位20通り (オッズ昇順)
- **AI予測**:
  - 上位5買い目 (確率・オッズ・EV)
  - **AIが「このレースで重視した特徴量Top5」** ★ (LightGBMのFeature Importance)
- **予測入力フォーム**:
  - 買い目入力 (例: "1-2-3, 1-2-4")
  - 投票金額入力 (任意、想定額)
  - 自信度 (1-5)
  - 一言メモ (任意)
  - 「保存」ボタン

#### 3. 対戦履歴
- 直近30レースの「AI予測 vs 自分の予測 vs 結果」を表形式で
- 列: 日付/会場/R/結果/AI買い目(的中?)/自分買い目(的中?)/AI ROI/自分 ROI

#### 4. 精度比較サマリ
- 月別 的中率比較 (棒グラフ: AI vs 自分)
- 累積 ROI 推移 (折れ線: AI vs 自分)
- 自信度別の的中率 (自信度高い時ほど当てている?)
- 「あなたが勝った/負けたレース」一覧

## データ構造

### 新規ファイル

#### `dashboard/public/daily_data/daily_race_info.json`
当日全レースの判断材料情報。朝バッチで生成。
```json
{
  "date": "2026-06-08",
  "races": [
    {
      "race_id": "20260608_若松_1",
      "venue": "若松", "r": 1, "race_time": "10:46",
      "weather": "晴", "wind_speed": 3, "wind_dir": "北",
      "wave": 1.0, "water_temp": 22.0,
      "boats": [
        { "lane": 1, "name": "選手A", "rank": "A1", "win_rate": 6.85,
          "venue_win_rate": 7.20, "st": 0.15, "motor_2in": 35.2,
          "weight": 52.0, "tilt": -0.5, "ex_time": 6.78,
          "venue_lane_p_win_rate": 0.62 },
        ...
      ],
      "odds_3t_top20": [
        { "combo": "1-2-3", "odds": 12.5 },
        ...
      ]
    }
  ]
}
```

#### `dashboard/public/daily_data/daily_feature_importance.json`
各レースでLightGBMが重要視した特徴量Top5。
```json
{
  "date": "2026-06-08",
  "by_race": {
    "20260608_若松_1": {
      "top5": [
        { "feature": "B1_VenueLanePWinRate", "value": 0.62, "importance": 0.18 },
        ...
      ]
    }
  }
}
```

#### ユーザー予測 (localStorage, key=`battle_predictions`)
```json
[
  {
    "race_id": "20260608_若松_1",
    "date": "2026-06-08",
    "venue": "若松", "r": 1,
    "picks": ["1-2-3", "1-2-4"],
    "stake": 200,
    "confidence": 4,
    "note": "1号艇強い、展示タイム上位",
    "timestamp": "2026-06-08T08:30:15"
  }
]
```

## 朝バッチ側変更

`morning_odds_runner.py` に以下を追加:
- 当日全レースの判断材料を `daily_race_info.json` に出力
- AI予測時に LightGBM feature_importance(importance_type="gain") から各レースの重要特徴量Top5を `daily_feature_importance.json` に出力

## 技術スタック

- フロント: 既存通り React 19 + Vite 7 + recharts + lucide-react
- データ取得: fetch (静的JSON/CSV)
- ユーザー予測保存: Phase 1 = localStorage、Phase 2 = Firebase (検討)
- 結果突き合わせ: 朝バッチ or 別バッチで `daily_history_results.csv` × 予測CSV をマージ → サマリJSON生成
- スマホ対応: CSS responsive (既存 index.css に media query 追加)

## 評価指標 (AI vs 自分)

- **的中率** (買い目のいずれかが的中したレース割合)
- **ROI** (回収÷投資)
- **自信度別的中率** (自信度高い時ほど当てる?)
- **月別推移**

## Phase 分割

### Phase 1 (本spec の範囲)
- 上記4セクション全部
- データ保存は localStorage
- 結果突き合わせは 別Pythonスクリプト (`auto_research/battle_summary.py`) でJSON生成

### Phase 2 (将来)
- クラウド同期 (Firebase/Supabase等)
- スマホ→PC自動同期
- レース直前のオッズ自動更新
- AIへのフィードバック (ユーザーが勝ったパターンを学習データに足す等)
