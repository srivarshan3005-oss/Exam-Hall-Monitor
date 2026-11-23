@echo off
rem Builds the STATIC portal from your database and PDFs and publishes it to GitHub Pages (branch gh-pages).
rem Needs: install.bat already run, Git installed and signed in to GitHub. Repo URL is set in publish_site.ps1.
setlocal
set "ROOT=%~dp0"

cd /d "%ROOT%backend"
if not exist ".venv\Scripts\python.exe" (
  echo The Python environment is missing. Run install.bat first.
  exit /b 1
)
echo [1/2] Building the static site from your database and PDFs...
".venv\Scripts\python.exe" build_static_site.py "%ROOT%site"
if errorlevel 1 (
  echo Build failed - see the message above.
  exit /b 1
)

echo [2/2] Publishing to GitHub Pages in small batches...
cd /d "%ROOT%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%publish_site.ps1"
if errorlevel 1 exit /b 1
echo.
echo Done. Your site (give GitHub 1-2 minutes the first time):
echo   https://srivarshan3005-oss.github.io/Exam-Hall-Monitor/
endlocal
