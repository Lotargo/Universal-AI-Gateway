@echo off
:: setup/install.bat

echo Starting installation for Magic Proxy...

:: --- 1. Check for Poetry ---
where poetry >nul 2>nul
if %errorlevel% neq 0 (
    echo Poetry could not be found. Installing Poetry...
    :: Using the recommended installer for PowerShell
    powershell -Command "(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -"
    echo Poetry installed successfully.
) else (
    echo Poetry is already installed.
)

:: --- 2. Install Dependencies ---
echo Installing project dependencies using Poetry...
poetry install

echo Installation complete.
