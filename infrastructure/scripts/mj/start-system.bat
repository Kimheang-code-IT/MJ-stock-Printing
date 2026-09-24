@echo off
setlocal
REM Stock & POS - start-system.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-system.ps1" %*
exit /b %ERRORLEVEL%

