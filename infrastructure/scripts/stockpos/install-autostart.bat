@echo off
setlocal
REM Stock & POS - install-autostart.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-autostart.ps1"
exit /b %ERRORLEVEL%

