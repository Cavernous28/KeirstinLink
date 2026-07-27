@echo off
setlocal

cd /d "%~dp0"

if not exist gradlew (
  echo [builder] gradlew not found. Install Android Studio or run:
  echo   gradle wrapper
  exit /b 1
)

gradlew assembleDebug
if %ERRORLEVEL% neq 0 (
  echo [builder] Android build failed.
  exit /b 1
)

echo [builder] APK: app\build\outputs\apk\debug\app-debug.apk
pause
