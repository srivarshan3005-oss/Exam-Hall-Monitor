@echo off
rem Runs the four required Gradle tasks and, if they succeed, records the debug APK's size and SHA-256.
rem Requires: JDK 17+, Android SDK (ANDROID_HOME or android\local.properties with sdk.dir=...), internet on first run.
setlocal
cd /d "%~dp0"
call gradlew.bat clean || goto :fail
call gradlew.bat testDebugUnitTest || goto :fail
call gradlew.bat assembleDebug || goto :fail
call gradlew.bat lintDebug || goto :fail
set APK=app\build\outputs\apk\debug\app-debug.apk
if not exist "%APK%" ( echo ERROR: %APK% is missing & goto :fail )
for %%F in ("%APK%") do echo APK: %%~fF  Size: %%~zF bytes
certutil -hashfile "%APK%" SHA256
echo.
echo BUILD OK
exit /b 0
:fail
echo.
echo BUILD FAILED - see the messages above. Nothing was installed.
exit /b 1
