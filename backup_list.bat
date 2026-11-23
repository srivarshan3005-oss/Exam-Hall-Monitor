@echo off
setlocal
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo Run install.bat first.& exit /b 1)
.venv\Scripts\python.exe -m app.cli backup-list
endlocal
