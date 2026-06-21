@echo off
REM Backfill blind predictions for past races. Loads credentials.env into env then runs python.
REM Usage: run_backfill.bat --models gemini --limit 200
REM        run_backfill.bat --models gemmaft,gemmaclaude
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)
python backfill_battle_predictions.py %*
