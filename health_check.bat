@echo off
setlocal EnableExtensions
cd /d "%~dp0backend"
if not exist ".venv\Scripts\python.exe" (echo ERROR: Run install.bat first.& exit /b 1)
echo === Configuration, database, storage, OCR, e-mail ===
".venv\Scripts\python.exe" -m app.cli health
set RC=%errorlevel%
echo.
echo === Monitoring status ===
".venv\Scripts\python.exe" -m app.cli status
echo.
echo === Running server ===
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:8000/api/ready; Write-Host ('server: ready (HTTP ' + $r.StatusCode + ')'); $s=Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 http://127.0.0.1:8000/api/public/status; Write-Host ('public status: HTTP ' + $s.StatusCode) } catch { Write-Host 'server: not running (run start.bat)'; exit 0 }"
exit /b %RC%
