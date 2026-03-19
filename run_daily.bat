@echo off
REM ==========================================
REM ボートレースAI 完全ローカル日次稼働スクリプト
REM ==========================================

REM LINE連携用の認証情報（credentials.env から読み込みます）
if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

REM 作業ディレクトリへ移動
cd /d "c:\Users\HP\OneDrive\ドキュメント\Play"

REM メイン処理の実行
REM ※将来、Anaconda等の仮想環境を使う場合はここにアクティベートコマンドを記載します
python main_runner.py

REM 完了（タスクスケジューラなどで動かすため、念のため少し待機）
timeout /t 5 >nul
