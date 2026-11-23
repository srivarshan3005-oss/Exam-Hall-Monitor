# Android release guide

**Status: no APK/AAB has been built in this project.** The build environment had no Android SDK, no Gradle distribution, only a JRE and no access to Google/Gradle repositories. Debug/unit tests were not run there either.

## Toolchain
JDK 17+ (Java/Kotlin target 17), Android SDK platform 35 + build-tools, Gradle wrapper 8.10.2 (AGP/Kotlin as pinned in `android/`), network access to Google Maven and Maven Central. `minSdk` 26, `targetSdk` 35.

## Backend URL (required for release)
Release tasks fail unless an HTTPS address is supplied; no default is compiled in:
```
cd android
./gradlew testDebugUnitTest
./gradlew assembleRelease -PAPI_BASE_URL=https://your-domain/      # Windows: gradlew.bat
```
`API_BASE_URL` may also be an environment variable. `http://` is rejected at build time and cleartext is disabled in release (`ALLOW_CLEARTEXT=false`). Debug builds default to `http://10.0.2.2:8000/`.

## Signing keystore
Create once and keep it **outside the repository and outside any ZIP**, with an offline backup (losing it prevents updating the app):
```
keytool -genkeypair -v -keystore exam-monitor-release.jks -alias exammonitor -keyalg RSA -keysize 4096 -validity 10000
```
Provide all four values as Gradle properties (`~/.gradle/gradle.properties`) or environment variables: `RELEASE_STORE_FILE` (absolute path), `RELEASE_STORE_PASSWORD`, `RELEASE_KEY_ALIAS`, `RELEASE_KEY_PASSWORD`. All four present: the release is signed. None present: unsigned artifact. Some present: the build fails (values are never printed). Never commit these values.

## Integration wiring (contract-tested, not device-tested)
Login/logout/profile/password endpoints, dashboards per role (student, staff, invigilator, admin), notifications (list, unread count, read/unread/archive, preferences), exams/announcements, results and the student seat/hall lookup (`api/lookup/{reg}`, allotments, hall reports) are declared in `data/Api.kt` and checked against the backend's OpenAPI paths by `tests/test_phase7_android_contract.py` (passing). The app has no VSB-specific screen: students see seats that exist as allotments (including VSB records only after an administrator has approved and published them). Verified only at API-contract level; behaviour on a device or emulator is untested. R8/minification is off and certificate pinning is not configured.
