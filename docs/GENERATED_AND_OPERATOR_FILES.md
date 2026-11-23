# Files that are created at runtime, at build time, or by the operator

Several paths mentioned in the documentation are **not** part of the package. They are created when the software is
installed, started, built or deployed, or they are supplied by the operator. Each row names the code or script that
creates the path. The link checker (`docs/` verification in `docs/archive/VALIDATION_REPORT_v6.md`, Appendix A) confirms that
each creator still contains the stated code, so this table cannot silently drift from the implementation.

| Path | Kind | Created or supplied by | Evidence (creator contains) |
|---|---|---|---|
| backend/.env | runtime | `install.bat` runs `python -m app.cli init-env` | `backend/app/cli.py`: `root / ".env"` |
| backend/.env.production | operator | copied from `backend/.env.production.example` | `backend/.env.production.example` exists |
| backend/.venv | runtime | `install.bat` creates the virtual environment | `install.bat`: `backend\.venv` |
| backend/outbox | runtime | mail outbox, created on first use | `backend/app/mailer.py`: `OUTBOX.mkdir` |
| backend/uploads | runtime | document storage, created on first PDF upload | `backend/app/routers/docproc.py`: `base.mkdir` |
| backend/backups | runtime | backup archives, created on first backup | `backend/app/data_management.py`: `BACKUP_DIR.mkdir` |
| backend/exam_monitor.db | runtime | default SQLite database, created by migration | `backend/app/config.py`: `exam_monitor.db` |
| backend/logs/server.err.log | runtime | server error log, created by `start.bat` | `start.bat`: `RedirectStandardError` |
| deploy/certs/fullchain.pem | operator | TLS certificate chain supplied by the operator | `deploy/certs/.gitkeep` exists |
| deploy/certs/privkey.pem | operator | TLS private key supplied by the operator | `deploy/certs/.gitkeep` exists |
| android/local.properties | operator | Android SDK location, supplied by the developer | `android/build_debug.bat`: `local.properties` |
| android/app/build/outputs/apk/debug/app-debug.apk | build | produced by `build_debug.bat` (`assembleDebug`) | `android/build_debug.bat`: `assembleDebug` |
| android/app/build/reports/lint-results-debug.html | build | produced by `lintDebug` | `android/build_debug.bat`: `lintDebug` |
| android/app/build/reports/tests/testDebugUnitTest/index.html | build | produced by `testDebugUnitTest` | `android/build_debug.bat`: `testDebugUnitTest` |

Files that the documentation mentions only as history (removed or replaced in a later build) are described in the
text of each document rather than linked.
