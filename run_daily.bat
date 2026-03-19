@echo off
REM ==========================================
REM ボートレースAI 完全ローカル日次稼働スクリプト
REM ==========================================

REM LINE連携用の認証情報
set LINE_CHANNEL_ACCESS_TOKEN=uJR1siSzBnpHvHKcfFhisUHHeAd5j1bwO3/KN55GMBGOhSTTXxoI6sMAqjhIw47IfIkeux3A9ZDeUzmBDhL7e0+5ZHPq+MfEsZg+3aXlDRVnVWREoNoIeCzXUvBNCrXk4j1oagodSOxUxXA9g+9+DQdB04t89/1O/w1cDnyilFU=
set LINE_USER_ID=U501f6d44ef2185eae2f221347e9cb235

REM 作業ディレクトリへ移動
cd /d "c:\Users\HP\OneDrive\ドキュメント\Play"

REM メイン処理の実行
REM ※将来、Anaconda等の仮想環境を使う場合はここにアクティベートコマンドを記載します
python main_runner.py

REM 完了（タスクスケジューラなどで動かすため、念のため少し待機）
timeout /t 5 >nul
