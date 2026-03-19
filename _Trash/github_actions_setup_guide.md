# GitHub Actions セットアップガイド

毎日自動でボートレースデータを収集するための設定手順です。

---

## 必要なもの（準備済み ✅）

- Google Service Account の JSON キー（`boatraceauto-6323885d1f1b.json`）
- Google ドライブの `boat_race_data` フォルダ

---

## STEP 1: GitHub リポジトリを作成

1. [GitHub](https://github.com/) にログイン
2. 右上の「**+**」→「**New repository**」をクリック
3. 設定：
   - Repository name: `boat-race-auto`
   - **Private**（プライベート）を選択 ← 重要！キー情報を守るため
   - 「Create repository」をクリック

---

## STEP 2: Google ドライブのフォルダIDを取得

1. ブラウザで Google ドライブの `boat_race_data` フォルダを開く
2. URL を確認：`https://drive.google.com/drive/folders/XXXXXXXXXX`
3. `XXXXXXXXXX` の部分をコピー（これが**フォルダID**）

---

## STEP 3: GitHub に秘密情報を登録（シークレット）

1. 作成した GitHub リポジトリを開く
2. 上部メニュー「**Settings**」をクリック
3. 左メニュー「**Secrets and variables**」→「**Actions**」
4. 「**New repository secret**」をクリック

### シークレット①：GDRIVE_API_KEY
- **Name**: `GDRIVE_API_KEY`
- **Secret**: ダウンロードした JSON ファイルの**中身をすべてコピペ**
  - `boatraceauto-6323885d1f1b.json` をメモ帳で開いて全選択コピー
- 「Add secret」をクリック

### シークレット②：DRIVE_FOLDER_ID
- **Name**: `DRIVE_FOLDER_ID`
- **Secret**: STEP 2 でコピーしたフォルダID
- 「Add secret」をクリック

---

## STEP 4: ファイルをアップロード

作成した GitHub リポジトリに、以下の2ファイルをアップロードします。

### 方法A: ブラウザから直接アップロード
1. リポジトリのメインページで「**Add file**」→「**Upload files**」
2. 以下のファイルをドラッグ＆ドロップ：
   - `collect_race_data.py`
   - `daily_scrape.yml`（⚠️ 注意：アップロード先のフォルダを変える必要あり）

### ⚠️ 重要：`daily_scrape.yml` の配置
`daily_scrape.yml` は **`.github/workflows/`** というフォルダに入れる必要があります。

1. リポジトリで「**Add file**」→「**Create new file**」
2. ファイル名に `.github/workflows/daily_scrape.yml` と入力
3. 本ファイルの中身（YAMLの内容）をコピペ
4. 「Commit new file」をクリック

---

## STEP 5: 動作確認（手動実行）

1. リポジトリ上部の「**Actions**」タブをクリック
2. 左側に「**Daily Race Data Collection**」が表示されていればOK
3. クリック → 右側の「**Run workflow**」→「**Run workflow**」（緑ボタン）
4. 実行されて緑のチェックマーク ✅ が出れば成功！

---

## 完了！ 🎉

設定完了後は、**毎日10:00 JST（日本時間）に自動実行** されます。
Google ドライブの `boat_race_data` フォルダに CSV ファイルが溜まっていきます。
