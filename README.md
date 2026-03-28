# ボートレースAI

LightGBM + DeepSeek-R1 による3連単予測・期待値最大化システム。

## 構成

| ファイル | 役割 |
|---|---|
| `main_runner.py` | 夜間バッチ（出走表取得 → LightGBM予測 → AI推論 → LINE通知） |
| `morning_odds_runner.py` | 朝バッチ（前売りオッズ取得 → EV計算 → AI予測更新 → LINE通知） |
| `local_ai_pipeline.py` | AI予測パイプライン本体 |
| `local_collect_race_data.py` | データ収集（出走表・結果・オッズ・直前情報） |
| `retrain_model.py` | LightGBMモデル自動再学習 |
| `generate_dashboard_data.py` | ダッシュボード用JSONデータ生成 |
| `database.py` | SQLite DB層（data/boatrace.db） |
| `build_features.py` | 特徴量エンジニアリング |

## バッチスケジュール

```
[毎日 23:00] run_daily.bat → main_runner.py
  - 翌日の出走表・選手成績取得
  - 当日の結果・直前情報・確定オッズ取得
  - LightGBM確率ベースのAI予測実行
  - LINE通知（夜間版）

[毎日 09:00] run_morning.bat → morning_odds_runner.py
  - 当日の前売りオッズ取得
  - LightGBM確率 × 実オッズ → EV算出
  - EV > 1.0 の買い目のみでAI予測を更新
  - Kelly基準でベット額を算出
  - LINE通知（EV強化版）
```

## Windowsタスクスケジューラへの登録手順

### 夜間バッチ（23:00）

1. タスクスケジューラを開く（`Win + R` → `taskschd.msc`）
2. 「タスクの作成」をクリック
3. 以下を設定：
   - **名前**: `BoatraceAI_Daily`
   - **トリガー**: 毎日 23:00
   - **操作**: プログラム = `C:\Users\HP\OneDrive\ドキュメント\Play\run_daily.bat`
   - **全般タブ**: 「ユーザーがログオンしているかどうかにかかわらず実行する」を選択

または PowerShell で一括登録：

```powershell
schtasks /create /tn "BoatraceAI_Daily" /tr "C:\Users\HP\OneDrive\ドキュメント\Play\run_daily.bat" /sc daily /st 23:00 /f
```

### 朝バッチ（09:00）

```powershell
schtasks /create /tn "BoatraceAI_Morning" /tr "C:\Users\HP\OneDrive\ドキュメント\Play\run_morning.bat" /sc daily /st 09:00 /f
```

> 朝バッチは登録済み（2026-03-29 に `BoatraceAI_Morning` として登録完了）。

### 登録確認

```powershell
schtasks /query /tn "BoatraceAI_Daily" /fo list
schtasks /query /tn "BoatraceAI_Morning" /fo list
```

## ダッシュボード

GitHub Pages: https://kids-masaru.github.io/Play/

`dashboard/` 以下のソースを変更して `main` にプッシュすると、GitHub Actions が自動ビルド＆デプロイします。

### ローカル確認

```bash
cd dashboard
npm install
npm run dev
```

## 初期セットアップ

```bash
pip install -r requirements.txt   # Python依存パッケージ
cd dashboard && npm install        # フロントエンド依存パッケージ
```

`.env` または `credentials.env` に以下を設定：

```
LINE_TOKEN=your_line_notify_token
```
