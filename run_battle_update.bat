@echo off
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [%date% %time%] ===== battle update start ===== >> "%~dp0logs\battle_update.log" 2>&1
python update_battle_dashboard.py >> "%~dp0logs\battle_update.log" 2>&1
echo [%date% %time%] ===== battle update end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\battle_update.log" 2>&1
