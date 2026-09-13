@echo off
setlocal
REM Stock & POS - install-desktop-shortcut.bat (forwards to PowerShell)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-desktop-shortcut.ps1"
exit /b %ERRORLEVEL%

