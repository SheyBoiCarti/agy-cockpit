@echo off
setlocal enabledelayedexpansion

:: Change directory to script location
cd /d "%~dp0"

:: Detect Python executable (.venv preferred)
if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

:: Ensure static frontend assets exist
if not exist "agy_cockpit\backend\static\index.html" (
    echo Static frontend assets not found. Building frontend...
    pushd "agy_cockpit\frontend"
    call npm run build
    popd
)

:: Check if workspace parameter was passed
set "HAS_WORKSPACE=0"
for %%A in (%*) do (
    if "%%~A"=="-w" set "HAS_WORKSPACE=1"
    if "%%~A"=="--workspace" set "HAS_WORKSPACE=1"
)

:: Launch with default workspace if not specified
if "%HAS_WORKSPACE%"=="0" (
    "%PYTHON%" -m agy_cockpit.cli --workspace "%cd%" %*
) else (
    "%PYTHON%" -m agy_cockpit.cli %*
)
