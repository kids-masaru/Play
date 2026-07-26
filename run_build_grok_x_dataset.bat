@echo off
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python gemma_finetune\data\build_grok_x_dataset.py 1000
pause
