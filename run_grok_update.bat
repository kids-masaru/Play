@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if not exist logs mkdir logs
set "LOG_FILE=%~dp0logs\grok_update.log"
echo ===== Grok update start %date% %time% ===== > "%LOG_FILE%"

call :main >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"

type "%LOG_FILE%"
echo.
if not "%EXIT_CODE%"=="0" echo ERROR: details saved to logs\grok_update.log
pause
exit /b %EXIT_CODE%

:main
if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python generate_grok_predictions.py
if errorlevel 1 exit /b 1

python generate_battle_data.py
if errorlevel 1 exit /b 1

echo Grok prediction and battle data updated.
exit /b 0
