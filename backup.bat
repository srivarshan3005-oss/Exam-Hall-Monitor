@echo off
setlocal
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo Run install.bat first.& exit /b 1)
.venv\Scripts\python.exe -m app.cli backup
if errorlevel 1 (echo Backup failed.& exit /b 1)
echo Verified backup created under backend\backups.
endlocal
