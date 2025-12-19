@echo off
:: run/run_server.bat

:: --- Configuration ---
:: Set to False to disable authentication (anonymous access)
:: set AUTH_ENABLED=True

echo Starting Universal AI Gateway server...
echo.
echo Server will be available at:
echo   - Dashboard/Registration: http://localhost:8001
echo   - Swagger UI:            http://localhost:8001/docs
echo   - API Base:              http://localhost:8001
echo   - Health:                http://localhost:8001/health
echo.

:: Install dependencies first (in case environment was recreated)
echo Installing dependencies...
call poetry lock
call poetry install --no-root
if %ERRORLEVEL% NEQ 0 (
    echo Error: Failed to install dependencies.
    pause
    exit /b %ERRORLEVEL%
)

:: Run the server using poetry to ensure the correct environment
:: --host 0.0.0.0 means "listen on all network interfaces"
:: Access via: http://localhost:8001 or http://127.0.0.1:8001
poetry run python -m uvicorn main:app --host 0.0.0.0 --port 8001 --reload
