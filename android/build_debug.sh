#!/usr/bin/env sh
# Runs the four required Gradle tasks and, if they succeed, records the debug APK's size and SHA-256.
# Requires: JDK 17+, Android SDK (ANDROID_HOME or android/local.properties with sdk.dir=...), internet on first run.
set -e
cd "$(dirname "$0")"
./gradlew clean
./gradlew testDebugUnitTest
./gradlew assembleDebug
./gradlew lintDebug
APK=app/build/outputs/apk/debug/app-debug.apk
[ -s "$APK" ] || { echo "ERROR: $APK is missing or empty"; exit 1; }
echo "APK: $APK"
echo "Size: $(wc -c < "$APK") bytes"
if command -v sha256sum >/dev/null 2>&1; then sha256sum "$APK"; else shasum -a 256 "$APK"; fi
