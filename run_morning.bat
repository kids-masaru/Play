@echo off
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

if not exist "%~dp0logs" mkdir "%~dp0logs"

rem ----- Playbook weekly review (Mondays only, LINE + report). No AI calls, finishes in seconds, never fails the batch. -----
echo [%date% %time%] ===== playbook weekly start ===== >> "%~dp0logs\morning.log" 2>&1
python playbook_weekly_report.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== playbook weekly end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1

echo [%date% %time%] ===== morning start ===== >> "%~dp0logs\morning.log" 2>&1
python morning_odds_runner.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== morning end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1

rem ----- Battle dashboard: copy -> generate (Det/LLM + Gemini) -> publish -----
echo [%date% %time%] ===== battle update start ===== >> "%~dp0logs\morning.log" 2>&1
python update_battle_dashboard.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== battle update end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1

rem ----- CLV: persist today's buy lists (accrues for scoring after closing odds) -----
echo [%date% %time%] ===== clv persist start ===== >> "%~dp0logs\morning.log" 2>&1
python compute_clv.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== clv persist end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1

rem ----- Playbook predictions (experiment only). Runs last so existing predictions and publishing are never delayed. -----
echo [%date% %time%] ===== playbook predict start ===== >> "%~dp0logs\morning.log" 2>&1
python playbook_predict.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== playbook predict end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1

rem ----- Jev for playbook arms (experiment only). Existing arms are reused from history (no extra API calls). -----
echo [%date% %time%] ===== playbook jev start ===== >> "%~dp0logs\morning.log" 2>&1
python jev_shadow.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== playbook jev end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1
