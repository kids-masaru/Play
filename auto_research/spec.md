# Auto Research 自己改善ループ - 仕様書

## 概要

Andrej Karpathy氏の「Auto Research」方式を参考に、Claude Codeが**ボートレース予測システムの特徴量エンジニアリングを自律的に改善する無期限ループ**を構築するサブシステム。

人間が寝ている間も、Claude Codeが `build_features.py` を書き換え → 学習 → 評価 → 良ければGitセーブ を延々繰り返すことで、ROI（回収率）を積み上げる。

## 技術スタック

- Python 3.x
- LightGBM（既存の `retrain_model.py` から流用）
- pandas, numpy, scikit-learn
- Git（セーブポイント機構）

## 機能要件

### 必須
1. `experiment.py`: 1試行の実験を実行し、ROI/的中率/取引回数/複合スコアを計測して `results.tsv` に追記する
2. `evaluator.py`: 予測結果・オッズ・実結果から評価指標を計算する（`generate_dashboard_data.py` のROI計算を流用）
3. `baseline.py`: 初期ベースラインを測定する
4. `program.md`: Claude Codeが実験ループを自律的に回すための指示書
5. `results.tsv`: 全試行履歴（trial_id, timestamp, git_hash, roi, hit_rate, n_trades, composite_score, change_summary, is_kept）

### 制約
- **実験対象は `build_features.py` のみ**（スコープ外: ハイパラ、モデル種類、LLMプロンプト、買い目選定ロジック）
- **時系列分割**を厳守（train: 〜検証期間-30日, val: 直近30日）
- ランダムシード固定（`random_state=42`）
- 1試行10分以内を目安
- Claude Codeは results.tsv を毎回読み、過去と重複する変更を提案しない

## 非機能要件

- 単一マシンで完結（GPU不要、LightGBM CPU学習）
- ネット接続不要（ローカルデータのみ使用）

## ディレクトリ構成

```
Play/
├── auto_research/
│   ├── spec.md            ← 本書
│   ├── task.md            ← 進捗管理
│   ├── program.md         ← Claude Code実験指示書
│   ├── evaluator.py       ← 評価指標計算
│   ├── experiment.py      ← 1試行実行
│   ├── baseline.py        ← 初期スコア測定
│   └── results.tsv        ← 試行履歴
└── build_features.py       ← 実験対象（既存・Claudeが書き換える）
```

## 評価指標

```
composite_score =
    roi_percent                              (メイン)
    - max(0, (MIN_TRADES - n_trades)) * 2    (取引少ペナルティ)
    - (99999 if hit_rate < 5 else 0)         (論外スコアは強制失格)
```

- **MIN_TRADES = 30**（検証期間30日で30件未満は実用性なし）
- 取引が多すぎる場合のペナルティは設けない（買い目選定ロジックが別途EVフィルタを持つため）

## 外部連携

なし（全てローカルファイル）。Gitのみ使用（セーブポイント機構）。

## 備考・制約

- 実験ループはClaude Codeのセッション内で動くため、一度止まったら再開コマンドが必要
- Gitコミットが大量になるため、定期的な `git log --oneline` での目視確認推奨
- build_features.py の変更履歴は `git log --follow build_features.py` で辿れる
