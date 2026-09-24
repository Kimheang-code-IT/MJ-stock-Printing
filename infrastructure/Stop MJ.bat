@echo off
setlocal
REM Stock & POS - stop the app safely (database and images are preserved).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\mj\stop-system.ps1" %*
echo.
echo Press any key to close.
pause >nul
exit /b %ERRORLEVEL%
