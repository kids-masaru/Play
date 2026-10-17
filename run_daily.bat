@echo off
setlocal
cd /d "%~dp0"

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python main_runner.py

rem Playbook reflection (experiment only). Runs after main_runner as a separate step.
rem Uses results up to today and builds the playbook for the next race day.
rem Failure here never affects predictions, purchases, LINE or publishing.
set PYTHONIOENCODING=utf-8
echo [%date% %time%] ===== playbook reflect start ===== >> "%~dp0logs\playbook_reflect.log"
python playbook_reflect.py --night >> "%~dp0logs\playbook_reflect.log" 2>&1
echo [%date% %time%] ===== playbook reflect end (exit=%errorlevel%) ===== >> "%~dp0logs\playbook_reflect.log"

timeout /t 5
