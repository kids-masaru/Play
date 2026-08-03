@echo off
setlocal
cd /d "%~dp0"

if not exist "reports" mkdir "reports"

echo.
echo ===== Codex prediction review =====
echo This run is read-only. It will not change models, predictions, or dashboard files.
echo.

where codex >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Codex CLI was not found. Open the Codex app once and sign in, then try again.
  echo.
  pause
  exit /b 1
)

codex exec --sandbox read-only --ask-for-approval never --output-last-message "reports\codex_prediction_review_latest.md" - < "codex_prediction_review_prompt.md"
if errorlevel 1 (
  echo.
  echo [ERROR] The review did not finish. Check that Codex is signed in and that your Codex usage is available.
  echo.
  pause
  exit /b 1
)

echo.
echo Done.
echo Report: %~dp0reports\codex_prediction_review_latest.md
echo.
pause
