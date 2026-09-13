@echo off
setlocal
REM Stock & POS - stop-system.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-system.ps1" %*
exit /b %ERRORLEVEL%

