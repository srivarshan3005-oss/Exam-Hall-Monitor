@echo off
setlocal
cd /d "%~dp0backend"
if not exist .run.pid (echo No managed server PID file found.& exit /b 0)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\managed_server.ps1" -Action stop -PidFile "%CD%\.run.pid"
del .run.pid >nul 2>nul
echo Stop request completed.
endlocal
