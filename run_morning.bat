@echo off
setlocal
cd /d "%~dp0"

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python morning_odds_runner.py
timeout /t 5
