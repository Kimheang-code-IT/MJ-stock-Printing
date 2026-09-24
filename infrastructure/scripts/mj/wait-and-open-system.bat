@echo off
setlocal
REM Stock & POS - wait-and-open-system.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wait-and-open-system.ps1" %*
exit /b %ERRORLEVEL%

