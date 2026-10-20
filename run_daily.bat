@echo off
setlocal
cd /d "%~dp0"

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

set PYTHONIOENCODING=utf-8
if not exist "%~dp0logs" mkdir "%~dp0logs"

rem ----- Wait until closing / morning batches finish so they do not fight over Ollama and AI APIs (max 3h, then start anyway). -----
python batch_lock.py start daily --wait-for closing morning --max-wait-minutes 180 >> "%~dp0logs\daily.log" 2>&1

rem ----- Main nightly run. Output is kept in logs\daily.log so slow steps can be found later. -----
echo [%date% %time%] ===== daily start ===== >> "%~dp0logs\daily.log" 2>&1
python main_runner.py >> "%~dp0logs\daily.log" 2>&1
echo [%date% %time%] ===== daily end (exit=%errorlevel%) ===== >> "%~dp0logs\daily.log" 2>&1

rem Playbook reflection (experiment only). Runs after main_runner as a separate step.
rem Uses results up to today and builds the playbook for the next race day.
rem Failure here never affects predictions, purchases, LINE or publishing.
echo [%date% %time%] ===== playbook reflect start ===== >> "%~dp0logs\playbook_reflect.log"
python playbook_reflect.py --night >> "%~dp0logs\playbook_reflect.log" 2>&1
echo [%date% %time%] ===== playbook reflect end (exit=%errorlevel%) ===== >> "%~dp0logs\playbook_reflect.log"

python batch_lock.py end daily >> "%~dp0logs\daily.log" 2>&1

timeout /t 5
