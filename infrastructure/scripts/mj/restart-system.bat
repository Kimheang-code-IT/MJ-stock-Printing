@echo off
setlocal
REM Stock & POS - restart-system.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-system.ps1" %*
exit /b %ERRORLEVEL%

