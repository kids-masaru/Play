@echo off
REM Build Gemma fine-tuning dataset (Gemini generates teacher reasoning). Loads credentials.env.
REM Usage:  run_build_dataset.bat          (default 80 races)
REM         run_build_dataset.bat 120       (specify count)
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python gemma_finetune\data\build_dataset.py %*
