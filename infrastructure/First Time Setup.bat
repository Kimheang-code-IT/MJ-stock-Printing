@echo off
setlocal
REM Stock & POS - first-time setup: create .env, build images, start the stack.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-client.ps1" -SkipGitPull %*
echo.
echo Setup finished. Press any key to close.
pause >nul
exit /b %ERRORLEVEL%
