@echo off
setlocal EnableExtensions
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (echo ERROR: Run install.bat first.& exit /b 1)
if not exist ".env" (echo ERROR: backend\.env missing. Run install.bat.& exit /b 1)
if exist ".run.pid" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\managed_server.ps1" -Action check -PidFile "%CD%\.run.pid" >nul 2>nul
  if not errorlevel 1 (echo ERROR: Managed server already appears to be running. Use stop.bat.& exit /b 1)
  del .run.pid >nul 2>nul
)
".venv\Scripts\python.exe" -m app.cli check-config
if errorlevel 1 (echo ERROR: Environment validation failed.& exit /b 1)
".venv\Scripts\python.exe" -m app.cli migrate
if errorlevel 1 (echo ERROR: Migration failed. See docs\MIGRATIONS.md.& exit /b 1)
if not exist logs mkdir logs
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process -FilePath '%CD%\.venv\Scripts\python.exe' -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000','--proxy-headers') -WorkingDirectory '%CD%' -RedirectStandardOutput '%CD%\logs\server.out.log' -RedirectStandardError '%CD%\logs\server.err.log' -PassThru -WindowStyle Hidden; Set-Content -Path '.run.pid' -Value $p.Id"
if errorlevel 1 (echo ERROR: Could not create server process.& exit /b 1)
set /a ATTEMPTS=0
:healthcheck
set /a ATTEMPTS+=1
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:8000/api/ready; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto healthy
if %ATTEMPTS% GEQ 20 goto failed
timeout /t 1 /nobreak >nul
goto healthcheck
:failed
echo ERROR: Server did not become healthy. Check backend\logs\server.err.log
call "%~dp0stop.bat"
exit /b 1
:healthy
echo Exam Monitor Ultimate is healthy.
echo Student search : http://127.0.0.1:8000/portal/   ^(register number only, no login^)
echo Management     : http://127.0.0.1:8000/          ^(administrator sign-in, "Live monitoring" page^)
echo Automatic scans: start with the server, then every 5 minutes.
echo API readiness: http://127.0.0.1:8000/api/ready
echo Logs: backend\logs\
echo Stop with stop.bat.
exit /b 0
