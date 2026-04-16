@echo off
chcp 65001 > nul
cd /d "C:\Users\HP\OneDrive\ドキュメント\Play"

:: credentials.env を読み込む
if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

echo [%date% %time%] ===== 自己改善ループ 起動 ===== >> auto_research\loop_log.txt 2>&1

:: Claude Code でループを実行
claude --dangerously-skip-permissions -p "@auto_research/program.md の指示に従って実験ループを開始してください" >> auto_research\loop_log.txt 2>&1

echo [%date% %time%] ===== 自己改善ループ 終了 ===== >> auto_research\loop_log.txt 2>&1

:: LINE に結果を通知
python auto_research\notify_loop_result.py >> auto_research\loop_log.txt 2>&1

echo [%date% %time%] 通知完了 >> auto_research\loop_log.txt 2>&1
