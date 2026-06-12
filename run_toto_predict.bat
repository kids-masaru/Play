@echo off
REM toto Gemini prediction wrapper. Loads credentials.env then runs predict_gemini.
REM Usage:  run_toto_predict.bat            (predict all on-sale rounds)
REM         run_toto_predict.bat 1635       (predict a specific round)
setlocal
cd /d "%~dp0"

set PYTHONIOENCODING=utf-8

if exist credentials.env (
    for /f "usebackq tokens=*" %%a in ("credentials.env") do set %%a
)

python toto\predict_gemini.py %*
