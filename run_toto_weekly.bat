@echo off
REM toto weekly orchestration. Loads credentials.env then runs run_toto_weekly.py.
REM Usage:  run_toto_weekly.bat                 (full run: fetch -> predict -> settle -> generate -> push)
REM         run_toto_weekly.bat --no-push       (generate only, no git push)
REM         run_toto_weekly.bat --skip-gemini   (no Gemini API call)
REM         run_toto_weekly.bat --skip-codex    (no Codex prediction)
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

if not exist "logs" mkdir "logs"
set "LOG_FILE=logs\toto_weekly.log"

echo [%date% %time%] ===== toto weekly start =====>> "%LOG_FILE%"
"%PYTHON_EXE%" toto\run_toto_weekly.py %* >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] ===== toto weekly end (exit=%EXIT_CODE%) =====>> "%LOG_FILE%"

exit /b %EXIT_CODE%
