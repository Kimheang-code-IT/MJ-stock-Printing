@echo off
setlocal
REM Stock & POS - remove-autostart.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0remove-autostart.ps1"
exit /b %ERRORLEVEL%

