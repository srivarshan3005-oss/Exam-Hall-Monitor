@echo off
setlocal
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo Run install.bat first.& exit /b 1)
echo WARNING: Stop the application and all workers before restoring.
set /p BACKUP_FILE=Enter backup ZIP filename from backend\backups: 
if "%BACKUP_FILE%"=="" (echo No filename supplied.& exit /b 1)
echo This operation replaces the configured database. A safety backup is created first.
set /p CONFIRM=Type RESTORE to continue: 
if /I not "%CONFIRM%"=="RESTORE" (echo Restore cancelled.& exit /b 1)
.venv\Scripts\python.exe -m app.cli restore-backup "%BACKUP_FILE%" --confirm-restore
if errorlevel 1 (echo Restore failed. Check the error and safety backup.& exit /b 1)
echo Restore completed. Run: python -m app.cli db-audit
endlocal
