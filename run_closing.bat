@echo off
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [%date% %time%] ===== closing start ===== >> "%~dp0logs\closing.log" 2>&1
python closing_odds_runner.py >> "%~dp0logs\closing.log" 2>&1
echo [%date% %time%] ===== closing end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\closing.log" 2>&1

rem ----- CLV recompute after closing odds captured -----
echo [%date% %time%] ===== clv compute start ===== >> "%~dp0logs\closing.log" 2>&1
python compute_clv.py >> "%~dp0logs\closing.log" 2>&1
echo [%date% %time%] ===== clv compute end (exit=%ERRORLEVEL%) ===== >> "%~dp0logs\closing.log" 2>&1
