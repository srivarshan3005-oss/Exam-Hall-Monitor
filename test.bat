@echo off
setlocal
cd /d "%~dp0backend"
if not exist .venv\Scripts\python.exe (echo Run install.bat first.& exit /b 1)
.venv\Scripts\python.exe -c "import pytest, httpx, aiosmtpd" >nul 2>nul
if errorlevel 1 (
  echo Test dependencies are not installed. Installing requirements-dev.txt...
  .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
  if errorlevel 1 (echo ERROR: Could not install test dependencies.& exit /b 1)
)
.venv\Scripts\python.exe -m pytest
exit /b %errorlevel%
