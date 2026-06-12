@echo off
REM toto weekly orchestration. Loads credentials.env then runs run_toto_weekly.py.
REM Usage:  run_toto_weekly.bat                 (full run: fetch -> predict -> settle -> generate -> push)
REM         run_toto_weekly.bat --no-push       (generate only, no git push)
REM         run_toto_weekly.bat --skip-gemini   (no Gemini API call)
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python toto\run_toto_weekly.py %*
