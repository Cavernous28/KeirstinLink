@echo off
setlocal enabledelayedexpansion

:: Build the bundled Python backend executable and the Tauri installer.
:: Run this from the repo root (KeirstinLink\).

cd /d "%~dp0"
set ROOT=%CD%
set RESOURCES=%ROOT%\src-tauri\resources

echo [builder] Building Python backend executable...
cd /d "%ROOT%\src-python"
python -m PyInstaller --onefile --name keirstinlink_backend --distpath "%RESOURCES%" --workpath "%ROOT%\build-pyinstaller" --specpath "%ROOT%\build-pyinstaller" --clean backend_entry.py
if %ERRORLEVEL% neq 0 (
    echo [builder] PyInstaller failed.
    exit /b 1
)

echo [builder] Backend executable: %RESOURCES%\keirstinlink_backend.exe

cd /d "%ROOT%"

echo [builder] Building Tauri installer...
cargo tauri build
if %ERRORLEVEL% neq 0 (
    echo [builder] Tauri build failed.
    exit /b 1
)

echo [builder] Done.
echo [builder] Installers should be in src-tauri\target\release\bundle\
pause
