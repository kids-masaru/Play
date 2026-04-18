@echo off
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [%date% %time%] ===== morning start ===== >> "%~dp0logs\morning.log" 2>&1
python morning_odds_runner.py >> "%~dp0logs\morning.log" 2>&1
echo [%date% %time%] ===== morning end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\morning.log" 2>&1
