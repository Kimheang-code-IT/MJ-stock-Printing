@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0clear-data.ps1" %*
endlocal
