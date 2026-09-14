@echo off
setlocal
REM Stock & POS - start the app, wait until healthy, then open the browser.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stockpos\wait-and-open-system.ps1" %*
exit /b %ERRORLEVEL%
