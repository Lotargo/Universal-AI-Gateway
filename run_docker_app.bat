@echo off
chcp 65001 > nul
setlocal

echo --- Universal AI Gateway Docker Launcher ---

:: Configuration
set APP_IMAGE_NAME=magic-proxy-app
set APP_CONTAINER_NAME=magic-proxy-app
set NETWORK_NAME=magpr1_shared_infra_net

:: Check Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not installed or not in PATH.
    pause
    exit /b 1
)

:: Check Network (should be created by setup_infra.bat)
docker network inspect %NETWORK_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Network '%NETWORK_NAME%' not found!
    echo Please run 'setup_infra.bat' first to initialize the infrastructure.
    pause
    exit /b 1
)

echo.
echo --- Building Application Image ---
docker build -t %APP_IMAGE_NAME% .
if %errorlevel% neq 0 (
    echo [ERROR] Docker build failed.
    pause
    exit /b 1
)

echo.
echo --- Stopping Previous Instance ---
docker stop %APP_CONTAINER_NAME% >nul 2>&1
docker rm %APP_CONTAINER_NAME% >nul 2>&1

echo.
echo --- Starting Application Container ---
echo.
echo Configuration:
echo   - Network: %NETWORK_NAME%
echo   - Ports:   8001:8001
echo   - Volume:  %cd% -^> /app
echo   - Redis:   shared-redis
echo   - Kafka:   shared-kafka:9092
echo   - Mongo:   shared-mongo:27017
echo.

:: Note: We run in foreground so you can see the logs immediately.
:: Use Ctrl+C to stop.
docker run ^
  --name %APP_CONTAINER_NAME% ^
  --network %NETWORK_NAME% ^
  -p 8001:8001 ^
  -e REDIS_HOST=shared-redis ^
  -e KAFKA_BROKER=shared-kafka:9092 ^
  -e MONGO_URL=mongodb://shared-mongo:27017 ^
  -v "%cd%":/app ^
  %APP_IMAGE_NAME%

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Container exited with error.
    pause
)
