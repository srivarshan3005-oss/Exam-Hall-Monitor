# Windows installation guide

Requirements: Windows 10/11, **Python 3.12 or newer from python.org** (the Microsoft Store "python" stub does not count). Optional: Tesseract OCR for scanned PDFs (see OCR.md).

1. Extract the ZIP to a path you control (e.g. `C:\ExamMonitor`).
2. Double-click `install.bat` (or run it in a terminal). It tries the `py -3` launcher, then `python`, and accepts only 3.12+; otherwise it stops with instructions. It then creates `backend\.venv`, installs dependencies, creates `backend\.env` with a generated `SECRET_KEY`, restricts that file's permissions (`scripts\configure_windows.ps1`), runs migrations (head 0013) and asks you to create the administrator.
3. Start with `start.bat` (also `run_windows.bat`). It runs the configuration check, applies migrations, starts uvicorn hidden on `127.0.0.1:8000`, records the PID in `backend\.run.pid` and waits for `/api/ready`.
4. Stop with `stop.bat`.
5. `backup.bat`, `backup_list.bat`, `restore_backup.bat`, `test.bat` as documented in BACKUP_RECOVERY.md and V7_TEST_REPORT.md.

## Process safety (start.bat / stop.bat)
Both scripts use `scripts\managed_server.ps1`. A PID file is honoured only when the PID is purely numeric, the process exists, its image is `python.exe`/`pythonw.exe` **and** its command line contains both `uvicorn` and `app.main:app`. If any test fails (stale file, reused PID, unrelated process) nothing is terminated and the file is treated as stale. When it matches, `taskkill /T /F` ends that process tree only.

## Verification status
Static review only; **the scripts have not been executed on Windows** (no Windows host was available). The same CLI steps (`init-env`, `check-config`, `migrate`, `db-audit`, `create-admin`) were run on Linux. First run on a real Windows machine: `install.bat`, `start.bat`, open `http://127.0.0.1:8000`, `stop.bat`, then confirm no python process remains and that an unrelated `python.exe` is never stopped.

## Opening the application
After `start.bat` reports healthy: admin application `http://127.0.0.1:8000/`, public student portal `http://127.0.0.1:8000/portal/` (add `?reg=REGISTER_NUMBER` to search directly). The ZIP ships **without** `backend\.env`, `backend\.venv` and the original VSB allocation data (`backend\data\original_portal\`, held by the operator); `install.bat` creates both (a fresh random `SECRET_KEY` is generated on your machine).

---

## Windows 10 installation and test instructions (for your own machine)

**Verification status: NOT VERIFIED ON WINDOWS.** The batch and PowerShell scripts were reviewed by reading them. They
have not been run on Windows in this project. The backend was tested on Python 3.14.10 on Linux, using the same
`requirements.txt`. Treat the steps below as the procedure to follow, and record what you actually observe in the
checklist at the end. Do not treat this document as evidence that the installation works.

### 1. Install Python 3.14 (64-bit) from python.org

1. Download the Windows x86-64 installer for Python 3.14 from https://www.python.org/downloads/windows/ (3.14.10 is the
   version the backend was tested on under Linux; any 3.14.x or newer 3.12+ release is accepted by `install.bat`).
2. On the first installer screen, tick **Install launcher for all users** and **Add python.exe to PATH**.
   The launcher (`py.exe`) is what `install.bat` uses first.
3. Do not use the Microsoft Store `python` entry; it is not the real interpreter.
4. Open **Command Prompt** and check:

   ```
   py -3.14 --version
   ```

   Expected output: `Python 3.14.10` (or another 3.14.x).

### 2. Unpack the release

Extract `Exam_Monitor_Ultimate_VSB_KARUR_FINAL_RELEASE.zip` to a plain folder such as
`C:\ExamMonitor\`. Avoid OneDrive or other synchronised folders, and avoid a read-only location, because the
installer writes `backend\.venv`, `backend\.env`, and the database.

### 3. Install

In Command Prompt:

```
cd /d C:\ExamMonitor\Exam_Monitor_Ultimate_VSB_KARUR_FINAL_RELEASE
install.bat
```

What `install.bat` does, from the script itself:

* finds `py -3`, then `python`, and accepts only Python 3.12 or newer. If it picks an older interpreter it stops with instructions;
* creates `backend\.venv` and installs `backend\requirements.txt` with pip;
* runs `scripts\configure_windows.ps1`, which asks for the college display name (press Enter to keep the current value)
  and writes `backend\.env` with a generated `SECRET_KEY`, then limits the file to the current user and SYSTEM. If that step fails it prints a warning, and you must restrict the file manually;
* runs the configuration check and applies the database migrations (`app.cli check-config`, `migrate`);
* creates the first administrator. It asks for a username (default `admin`) and a password typed twice. The password must be at
  least 12 characters with letters and digits. Write it down; it is not stored anywhere else. If admin creation is not completed, the installer prints a `NOTE:` line with the command to run afterwards.

If the installer reports a problem, read the message. It is printed in the same window.

### 4. Optional: keep development mail out of the program folder

`install.bat` does not set this. Open `backend\.env` in Notepad and add:

```
MAIL_OUTBOX_DIR=C:\ExamMonitorOutbox
```

Leave `SMTP_HOST` blank for a test computer. Without it, mail is written as text files to that folder and never sent. If the
path is unusable (for example, a file exists with that name), `check-config` reports it and no mail is written anywhere else.
Blank keeps the default folder, `backend\outbox`.

### 5. Start, open and stop

```
start.bat
```

`start.bat` runs the configuration check, applies migrations, and starts the server hidden on `127.0.0.1:8000`. It records the
process in `.run.pid`, refuses to start a second copy, and checks `/api/ready` before reporting success.

Open in your browser:

* administration: `http://127.0.0.1:8000/` (sign in with the administrator account created during installation);
* public student portal: `http://127.0.0.1:8000/portal/` (add `?reg=` and the 12-digit register number, for example
  `http://127.0.0.1:8000/portal/?reg=992696352326`, to search directly).

Stop the server:

```
stop.bat
```

`stop.bat` stops only the process recorded in `.run.pid`, and only if that process is still a Python process running
`app.main:app`. Run `start.bat` again to restart.

### 6. Import the original hall-allocation data (administrator, optional)

1. Sign in, open **VSB hall & seat**.
2. Choose `backend\data\original_portal\source\allotments.json`.
3. Press **Dry run** and read the summary. It writes nothing.
4. Press **Stage as drafts** only if you intend to review. Nothing is shown to students until each batch is reviewed and published.

See `ORIGINAL_PORTAL_IMPORT.md` for what each flag means and what must be checked against the official PDFs.

### 7. Run the automated tests

```
test.bat
```

`test.bat` checks for the virtual environment, installs `requirements-dev.txt` if pytest, httpx or aiosmtpd is missing, and runs `pytest`
inside `backend\.venv`. The last line shows the totals. On Linux the totals were 636 passed and 24 skipped. The skips are
21 PostgreSQL tests (they need `TEST_POSTGRES_URL` set to a PostgreSQL database) and 3 tests that need real VSB notice
fixtures, which are deliberately not distributed. Your Windows totals may differ; record them.

`run_test.bat` starts a test server on port 8765 and writes its log to `C:\Temp\uvicorn_test.log`. Create the folder
`C:\Temp` first, or use `test.bat` instead. 

The front-end browser-flow checks use Node.js and jsdom. They are optional and are not part of `test.bat`.

### 8. Windows checklist (record the actual result of each step)

| # | Step | Expected | Observed (you fill in) |
|---|------|----------|------------------------|
| 1 | `py -3.14 --version` | `Python 3.14.x` | |
| 2 | `install.bat` completes | ends without an ERROR line; backend\.venv exists | |
| 3 | `backend\.env` exists and has a SECRET_KEY | yes | |
| 4 | `start.bat` reports the server is ready | success message | |
| 5 | `http://127.0.0.1:8000/` shows the sign-in page | page loads | |
| 6 | Sign in as the administrator | dashboard opens | |
| 7 | `http://127.0.0.1:8000/portal/?reg=992696352326` | portal loads and searches | |
| 8 | Stage the original file (dry run, then stage) | 3,306 rows valid, 0 rejected | |
| 9 | Sample register after publication | hall MB III A103, seat 23 | |
| 10 | `stop.bat` | prints "Stopped managed server process <pid>"; the server no longer answers | |
| 11 | `start.bat` again | server starts again | |
| 12 | `test.bat` | pytest totals shown | |

### 9. Troubleshooting

* **"Python 3.12 or newer was not found"**: the `py` launcher is missing or the installer did not add Python to PATH.
  Re-run the Python installer and choose *Modify*, then tick the launcher.
* **Scripts blocked by PowerShell**: the scripts call PowerShell with `-ExecutionPolicy Bypass` for that script only. Do not change the
  machine-wide policy to run them.
* **Port 8000 already in use**: `start.bat` uses port 8000 and does not choose another. Close the other program that uses it.
* **Antivirus or SmartScreen blocks a script or `.venv` program**: allow the release folder in your security product, then run again.
* **Tesseract OCR**: optional, only for scanned PDFs. Not needed for this installation.
