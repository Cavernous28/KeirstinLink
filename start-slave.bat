@echo off
REM KeirstinLink Windows slave launcher
REM Usage: start-slave.bat [task_json_or_task_id]

setlocal EnableDelayedExpansion

cd /d "%~dp0"

if not exist .env (
    echo [KeirstinLink] .env not found. Copy .env.example to .env and fill it in.
    exit /b 1
)

for /f "tokens=1,2 delims==" %%A in (.env) do (
    set "%%A=%%B"
)

set "TASK=%~1"
if "%TASK%"=="" (
    echo [KeirstinLink] No task provided. Usage: start-slave.bat ^<task_json_or_task_id^>
    exit /b 1
)

echo [KeirstinLink] Starting slave with task: %TASK%
python -m src.slave --task %TASK% --callback-url http://%KL_MASTER_HOST%:%KL_MASTER_PORT%/callback
