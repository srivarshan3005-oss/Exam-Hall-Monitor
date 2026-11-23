# Exam Monitor - Android app (Phase 7.1, v0.8.1)

Kotlin - Jetpack Compose - Material 3 - MVVM - Repository pattern - Retrofit/OkHttp - Coroutines/Flow - Navigation Compose.
It talks to the **existing FastAPI backend** (no new endpoints, no separate database, no mock data).

**Build status: NOT built - no APK is included in this package.** The environment used for Phase 7 and 7.1 has no Android SDK and
cannot reach Google Maven / Maven Central / dl.google.com (`./gradlew` starts, then fails resolving the Android Gradle Plugin -
captured in `docs/archive/PHASE71_GRADLE_ATTEMPT.txt`). `clean`, `testDebugUnitTest`, `assembleDebug` and `lintDebug` have therefore **never been
run**. Phase 7.1 found and fixed three genuine compile errors and one UI logic bug by source review (see "Phase 7.1 changes").
Further compile/lint errors may still exist; fix them on the first real build. Exact commands are below.

## Requirements
* Android Studio Ladybug (2024.2) or newer, JDK 17, Android SDK Platform 35 (min SDK 26 = Android 8.0, target/compile SDK 35).
* Internet access on first Gradle sync (dependencies are downloaded from Google Maven / Maven Central).
* Gradle wrapper 8.10.2 is included (`gradlew`, `gradlew.bat`, `gradle/wrapper/*`); the Gradle distribution itself is downloaded on first use.

## Build (the commands to run on a machine with the Android SDK)
Prerequisites: JDK 17 or newer (Android Studio's bundled JBR is fine), Android SDK Platform 35 + Build-Tools (install via Android Studio
> SDK Manager), internet on the first run (Gradle 8.10.2 and all libraries are downloaded). Create `android/local.properties` containing
`sdk.dir=C\:\\Users\\<you>\\AppData\\Local\\Android\\Sdk` (Windows) or `sdk.dir=/home/<you>/Android/Sdk` (Linux/macOS) if Android Studio has not
created it (or set `ANDROID_HOME`). Never commit this file.

Windows (from `android\`):
```
gradlew.bat clean
gradlew.bat testDebugUnitTest
gradlew.bat assembleDebug
gradlew.bat lintDebug
```
Linux/macOS: the same with `./gradlew`. Or run everything and get the APK's size and SHA-256 in one go:
`build_debug.bat` (Windows) / `./build_debug.sh`.

* Debug APK: `android/app/build/outputs/apk/debug/app-debug.apk` (signed with the automatic debug key).
* Unit-test report: `android/app/build/reports/tests/testDebugUnitTest/index.html`; lint report: `android/app/build/reports/lint-results-debug.html`.
* Release APK: `gradlew.bat assembleRelease -PAPI_BASE_URL=https://exams.your-university.edu/` (Linux/macOS: `./gradlew assembleRelease ...`; the wrapper script is executable in the release ZIP).
  The release build rejects an explicitly supplied non-HTTPS API URL. Without signing inputs, Gradle produces an unsigned release artifact.
* Optional release signing: keep your keystore outside the repository and supply all four values as Gradle properties or environment
  variables: `RELEASE_STORE_FILE` (use an absolute path), `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_ALIAS`, and `RELEASE_KEY_PASSWORD`.
  `app/build.gradle.kts` creates a `release` signing configuration from them and attaches it to the `release` build type when all four
  are present. If only some are set, any release task fails and names the missing values; if the keystore path does not exist it fails
  too. If none are set the release artifact is unsigned. This wiring has **not** been exercised by a Gradle run yet.
  Example (PowerShell, current session only):
  ```powershell
  $env:RELEASE_STORE_FILE = "C:\secure\exam-monitor-release.jks"
  $env:RELEASE_STORE_PASSWORD = "<from-secret-manager>"
  $env:RELEASE_KEY_ALIAS = "<key-alias>"
  $env:RELEASE_KEY_PASSWORD = "<from-secret-manager>"
  .\gradlew.bat assembleRelease -PAPI_BASE_URL=https://exams.your-university.edu/
  ```
  Do not put signing passwords in source control, `gradle.properties`, command history, or the release ZIP.
  `isMinifyEnabled` remains false; shrinking/obfuscation has not been configured or validated for this app.
* If the build fails, send the first `error:` / `e: file://...` lines; most likely places are `ui/` (Compose) and `lintDebug` findings.

## Install the debug APK
1. Emulator: start an AVD (API 26+), then `adb install -r app\build\outputs\apk\debug\app-debug.apk` (or drag the APK onto the emulator).
2. Physical device: enable Developer options > USB debugging, connect, run the same `adb install -r ...`; or copy the APK to the phone and open it
   (allow "install unknown apps" for the file manager). Uninstall first if an older build signed with a different key is installed.
3. Verify the download before installing: `certutil -hashfile app-debug.apk SHA256` (Windows) / `sha256sum app-debug.apk` and compare with the
   value printed by `build_debug.bat` / recorded in `docs/V7_TEST_REPORT.md` once a real build exists.

## API configuration
* Debug default: `http://10.0.2.2:8000/` (the emulator's alias for the PC running `start.bat`). Cleartext HTTP is permitted **only** in the debug build (`src/debug`).
* Release: **no default address**. `assembleRelease`/`bundleRelease` fail unless `-PAPI_BASE_URL=https://your-domain/` (or env `API_BASE_URL`) is given; `http://` is refused. See docs/ANDROID_RELEASE.md.
* On the login screen, **Server settings** lets the user change the address (only while signed out). The address is validated (HTTPS required in release).
* Physical device on the same Wi-Fi: start the backend bound to a LAN address (see docs/WINDOWS_INSTALLATION.md), allow it through the firewall, and enter `http://<PC-LAN-IP>:8000/` in a **debug** build.
* Production: serve the API over HTTPS with a valid certificate (certificate pinning is not configured - see limitations).

## Emulator / device testing
1. Start the backend (`start.bat`), create users in the web portal (or `python -m app.cli create-admin`): at least one account per role
   (student linked to a student record with seat allotments and a published result, staff, administrator, invigilator).
2. **Emulator:** the debug build already points at `http://10.0.2.2:8000/` (the emulator's alias for the PC).
   **Physical device on the same Wi-Fi:** start the backend bound to a LAN address (see `docs/WINDOWS_INSTALLATION.md`), allow it through the Windows firewall,
   then on the login screen open *Server settings* and enter `http://<PC-LAN-IP>:8000/` (debug builds only; release builds refuse `http://`).
3. Walk the checklist in `docs/archive/PHASE7_ANDROID.md` ("Manual test checklist") for every role. At minimum: login/logout; kill and reopen the app
   (session restored); revoke the session in the web portal and pull to refresh (returns to login with a message); airplane mode (cached
   timetable/results shown with the "Saved copy" banner); sign in as a second account and confirm the first account's data is gone; wrong
   password; locked/rate-limited account message; notification list, unread badge, mark read/unread, archive, preferences; publish/unpublish as staff.
4. `adb logcat | findstr ExamMonitor` (or Logcat in Android Studio) should show **no** tokens, passwords or student data - the app has no logging.

## What the app does
| Role | Tabs |
|---|---|
| Student | Home (next exam, unread, announcements) - Timetable (own hall/seat, exam details) - Results (own, published) - Alerts - Profile |
| Staff / Administrator / Super administrator | Home (statistics, upcoming exams) - Exams (search/filter, detail with summary/halls/allocations, publish/unpublish with confirmation) - Students (seat lookup) - Alerts - Profile |
| Invigilator | Home - Exams (read-only detail: halls and allocations) - Alerts - Profile |

Everyone: login/logout, forced password change, "forgot password" (e-mailed link, paste link/code in the app), notification centre (read/unread, archive, mark all read, paging, pull-to-refresh, details, preferences), announcements, light/dark/system theme.
Complex workflows (allocation runs, PDF/OCR import, results publishing, account management) are deliberately **not** in the app; screens point to the web portal.

## Security design
* Bearer token (and last profile) kept in `EncryptedSharedPreferences` (Android Keystore AES-256). Passwords are never stored, logged or saved in instance state.
* No logging interceptor exists, so tokens and student data are never written to Logcat.
* HTTP 401 on an authenticated call ends the session, wipes the token and every cache and returns to login with a message.
* Cached read-only data (timetable, results, exams, announcements, dashboard) is encrypted, namespaced per user and wiped on logout, expiry and account switch. Lookups of other people's records and notifications are never cached.
* All ViewModels holding private data live in one store that is emptied at sign-out, so the next user on the device cannot see old state.
* Student screens call the API only with the register number from the signed-in profile; the backend additionally refuses other numbers for results.
* Server responses are validated (`Mappers`): missing required fields become a clear "unexpected response" error instead of a crash.
* Backups disabled (`allowBackup=false`, data-extraction rules exclude everything).

## Phase 7.1 changes (found by source review - no compiler for Android was available)
| Fix | File | Why it matters |
|---|---|---|
| Added missing import `androidx.compose.runtime.saveable.rememberSaveable` | `ui/screens/StaffScreens.kt` | `runtime.*` does not cover the `saveable` package - **unresolved reference, would fail `assembleDebug`** |
| `@OptIn(ExperimentalMaterial3Api::class)` on `StateHost` and `NotificationList` | `ui/components/Components.kt`, `ui/screens/AlertsScreens.kt` | `PullToRefreshBox` is experimental in Material3 1.3.x (BOM 2024.12.01) - **opt-in error** |
| Replaced `a.location?.let { ... } ?: Text(...)` with an explicit `if/else` | `ui/screens/StudentScreens.kt` | Logic bug: the "location not published" text was shown whenever the *last* location field (room) was empty, even when building/block/floor were displayed |
| `gradle.properties`: heap 4 GB, `android.nonTransitiveRClass`, `kotlin.code.style` | `gradle.properties` | Precaution: Compose + lint can exhaust a 2 GB daemon (not observed - never built) |
| Version 0.8.1 / versionCode 3 | `app/build.gradle.kts` | Distinguishes the corrected source |
| Added `build_debug.bat` / `build_debug.sh` | `android/` | Runs the four required tasks and prints the APK size + SHA-256 |

## Verification (what was and was not run - Phase 7.1, 14 Nov 2026)
| Check | Result |
|---|---|
| `./gradlew clean`, `testDebugUnitTest`, `assembleDebug`, `lintDebug` | **COULD NOT RUN** - Android Gradle Plugin 8.7.3 cannot be resolved (Google Maven unreachable), no Android SDK. Output: `docs/archive/PHASE71_GRADLE_ATTEMPT.txt` |
| Project's own `gradlew` + wrapper jar with Gradle 8.10.2 (distribution from GitHub releases; SHA-256 31c55713...c26) | **Works**: Gradle starts, `settings.gradle.kts` and root `build.gradle.kts` compile; stops only at plugin download |
| Android core tests (25: roles/navigation, errors/validation, dates/timetable/notification logic, isolation/mapping) | **25 passed, 0 failed** - `core/` + `CoreLogicTest.kt` compiled with the real kotlinc 2.0.21 and run on JDK 21 with a minimal JUnit API shim (`docs/archive/PHASE71_ANDROID_CORE_TEST_RESULTS.txt`). This is *not* `testDebugUnitTest` |
| `DataLayerTest.kt` (session, cache, repositories, interceptors, MockWebServer) | **Not run** - needs Gson/OkHttp/Retrofit/MockWebServer from Maven. Read for compile errors: none found |
| Compose UI, Navigation, manifest merge, resources, AAPT, R8, lint | **Not compiled** - reviewed by hand and with an import/opt-in audit script (3 defects found and fixed, above) |
| Full backend suite (API compatibility) | **477 passed, 0 failed, 0 skipped** (Python 3.12, fresh venv; `docs/archive/PHASE71_BACKEND_FULL_TEST_RESULTS.xml`). `tests/e2e_jsdom` (Node) not run |
| Backend contract used by the app (`test_phase7_android_contract.py`, 10 tests) | passed (part of the 477) |
| Endpoint paths/params the app sends vs backend routes (`/api/admin/reports/...`, `/api/allotments/exam/{id}`, notification `status`/`limit`, `X-Total-Count`, 403 for wrong current password) | Checked against the router source - consistent |
| Emulator / physical device functional testing | **Not done** (no emulator, no device, no SDK) |
| APK | **Not produced. No APK exists in this package.** |

## Known limitations
* **Push notifications are pending.** No push provider (FCM) or backend device-token API exists. Notifications are in-app, refreshed on open/pull-to-refresh and when the Alerts/Home screen loads. The Phase 6 scheduler's reminders and announcement notices appear in the list.
* The public `/api/lookup/{register}` endpoint is unauthenticated by design in the backend; the app only ever calls it with the signed-in student's own number, but the server itself does not bind it to the account.
* Password reset: the e-mail contains a web link (`?reset=`); the app has no deep link - the user pastes the link or code.
* Self-registration/activation is web-only. Roster views are limited to the first 200 allocations. Staff exam list loads up to 100 exams.
* No certificate pinning, no root/jailbreak detection, no FLAG_SECURE (screenshots are allowed), R8/minification is off.
* The Android build has never been run (see Verification): expect a few compile/lint errors on the first real build.
* Release signing, Play Store packaging, accessibility audit with TalkBack, tablet layouts and localisation are not done.
