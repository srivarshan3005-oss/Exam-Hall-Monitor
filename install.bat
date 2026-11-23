@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo ============================================================
echo Exam Monitor Ultimate - Windows installation
echo ============================================================
set "PYCMD="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
  if not errorlevel 1 set "PYCMD=py -3"
)
if not defined PYCMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
    if not errorlevel 1 set "PYCMD=python"
  )
)
if not defined PYCMD (
  echo ERROR: Python 3.12 or newer was not found ^(tried the "py" launcher, then "python"^).
  echo Install Python 3.12 or newer from https://www.python.org/downloads/windows/
  echo Select "Install launcher for all users" and "Add python.exe to PATH".
  echo Note: the Microsoft Store "python" stub does not count; install the real Python.
  exit /b 1
)
echo Using Python: %PYCMD%
%PYCMD% -c "import sys; v=sys.version_info[:2]; print('Python', '.'.join(map(str,v))); print('NOTE: only Python 3.12 was verified for this release (3.13/3.14 are untested).' if v!=(3,12) else 'Python 3.12 - the verified version.')"
if not exist "backend\.venv\Scripts\python.exe" (
  echo [1/6] Creating isolated virtual environment...
  %PYCMD% -m venv "backend\.venv"
  if errorlevel 1 (echo ERROR: Virtual environment creation failed.& exit /b 1)
) else echo [1/6] Existing virtual environment found.
echo [2/6] Upgrading pip...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (echo ERROR: pip upgrade failed. Check network/proxy settings.& exit /b 1)
echo [3/6] Installing application dependencies...
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 (echo ERROR: Dependency installation failed. See docs\WINDOWS_INSTALLATION.md.& exit /b 1)
echo [4/6] Creating secure local configuration...
pushd backend
".venv\Scripts\python.exe" -m app.cli init-env
if errorlevel 1 (popd& echo ERROR: Could not create backend\.env.& exit /b 1)
popd
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_windows.ps1"
if errorlevel 1 (echo ERROR: Configuration wizard failed. Review backend\.env and retry.& exit /b 1)
echo [5/6] Validating configuration...
pushd backend
".venv\Scripts\python.exe" -m app.cli check-config
if errorlevel 1 (popd& echo ERROR: Configuration validation failed.& exit /b 1)
echo [6/6] Applying additive database migrations...
".venv\Scripts\python.exe" -m app.cli migrate
if errorlevel 1 (popd& echo ERROR: Database migration failed. Existing data has not been intentionally deleted. See docs\MIGRATIONS.md.& exit /b 1)
".venv\Scripts\python.exe" -m app.cli db-audit
if errorlevel 1 (popd& echo ERROR: Database audit reported issues. Review the output before starting.& exit /b 1)
popd
echo.
echo [check] Running health check...
pushd backend
".venv\Scripts\python.exe" -m app.cli health
popd
echo.
echo Installation completed.
echo.
echo The student website needs NO account and NO password.
set "MKADMIN="
set /p MKADMIN=Create an administrator account for the management dashboard now? [Y/N]: 
if /i "%MKADMIN%"=="Y" (
  pushd backend
  ".venv\Scripts\python.exe" -m app.cli create-admin --username admin
  if errorlevel 1 echo NOTE: Admin creation was not completed. Run later: cd backend ^& .venv\Scripts\python.exe -m app.cli create-admin --username admin
  popd
)
echo.
echo NEXT STEPS
echo   1. Run start.bat
echo   2. Students: open http://127.0.0.1:8000/portal/  and enter a register number
echo   3. Administrators: open http://127.0.0.1:8000/  ^(Live monitoring page^)
exit /b 0
