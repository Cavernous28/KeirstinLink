@echo off
REM KeirstinLink Windows backend launcher
REM Usage: start-backend.bat

setlocal EnableDelayedExpansion

cd /d "%~dp0"

if not exist .env (
    echo [KeirstinLink] .env not found. Copy .env.example to .env and fill it in.
    exit /b 1
)

for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
    set "%%A=%%B"
)

echo [KeirstinLink] Starting backend on %KL_HOST%:%KL_PORT%
cd src-python
python -m keirstin_link.main --host %KL_HOST% --port %KL_PORT%
