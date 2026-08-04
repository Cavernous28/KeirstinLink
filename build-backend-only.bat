@echo off
setlocal enabledelayedexpansion

cd /d "C:\Users\cbaxt\git\KeirstinLink\src-python"

C:\Users\cbaxt\git\KeirstinLink\build-venv-uv\Scripts\python.exe -m PyInstaller --onefile --name keirstinlink_backend --add-data "C:\Users\cbaxt\git\KeirstinLink\src;src" --distpath "C:\Users\cbaxt\git\KeirstinLink\src-tauri\resources" --workpath "C:\Users\cbaxt\git\KeirstinLink\build-pyinstaller" --specpath "C:\Users\cbaxt\git\KeirstinLink\build-pyinstaller" --clean backend_entry.py

if %ERRORLEVEL% neq 0 (
    echo PyInstaller failed.
    exit /b 1
)

echo Backend built.
pause
