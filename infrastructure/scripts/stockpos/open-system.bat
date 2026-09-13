@echo off
setlocal
REM Stock & POS - open-system.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0open-system.ps1" %*
exit /b %ERRORLEVEL%

