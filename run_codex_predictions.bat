@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===== Codex prediction update =====
set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
"%PYTHON_EXE%" generate_codex_predictions.py
if errorlevel 1 goto :error
"%PYTHON_EXE%" generate_battle_data.py
if errorlevel 1 goto :error
echo.
echo Codex prediction and battle data updated.
pause
exit /b 0

:error
echo.
echo [ERROR] Codex prediction update failed.
pause
exit /b 1
