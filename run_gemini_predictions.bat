@echo off
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python generate_gemini_predictions.py
