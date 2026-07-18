@echo off
REM KeirstinLink Windows master launcher
REM Usage: start-master.bat

setlocal EnableDelayedExpansion

cd /d "%~dp0"

if not exist .env (
    echo [KeirstinLink] .env not found. Copy .env.example to .env and fill it in.
    exit /b 1
)

for /f "tokens=1,2 delims==" %%A in (.env) do (
    set "%%A=%%B"
)

echo [KeirstinLink] Starting master bridge on %KL_MASTER_HOST%:%KL_MASTER_PORT%
python -m src.master --host %KL_MASTER_HOST% --port %KL_MASTER_PORT%
