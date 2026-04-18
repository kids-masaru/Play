@echo off
setlocal
cd /d "%~dp0.."

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

echo [%date% %time%] ===== loop start (cwd=%CD%) ===== >> "%~dp0loop_log.txt" 2>&1

claude --dangerously-skip-permissions -p "@auto_research/program.md" >> "%~dp0loop_log.txt" 2>&1
set CLAUDE_EXIT=%ERRORLEVEL%
echo [%date% %time%] ===== loop end (claude exit=%CLAUDE_EXIT%) ===== >> "%~dp0loop_log.txt" 2>&1

python "%~dp0notify_loop_result.py" >> "%~dp0loop_log.txt" 2>&1
set NOTIFY_EXIT=%ERRORLEVEL%
echo [%date% %time%] notify done (exit=%NOTIFY_EXIT%) >> "%~dp0loop_log.txt" 2>&1
