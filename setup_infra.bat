@echo off
chcp 65001 > nul
setlocal

echo --- Setting up Infrastructure (Redis + Kafka + MongoDB) ---

:: Configuration
set NETWORK_NAME=magpr1_shared_infra_net
set REDIS_CONTAINER_NAME=shared-redis
set KAFKA_CONTAINER_NAME=shared-kafka
set MONGO_CONTAINER_NAME=shared-mongo

set REDIS_VOLUME_NAME=redis-data
set KAFKA_DATA_VOLUME_NAME=kafka-data
set KAFKA_SECRETS_VOLUME_NAME=kafka-secrets
set MONGO_VOLUME_NAME=mongo-data

set REDIS_IMAGE=redis:7-alpine
set KAFKA_IMAGE=confluentinc/cp-kafka:latest
set MONGO_IMAGE=mongo:latest

:: Check Docker
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not installed or not in PATH.
    exit /b 1
)

:: Docker Login
echo Authenticating to Docker Hub...

:: Load .env file
if exist .env (
    for /f "tokens=1* delims==" %%a in ('type .env') do (
        set %%a=%%b
    )
)

if "%DOCKER_USERNAME%"=="" (
    echo [ERROR] DOCKER_USERNAME not set in .env or environment.
    exit /b 1
)
if "%DOCKER_ACCESS_TOKEN%"=="" (
    echo [ERROR] DOCKER_ACCESS_TOKEN not set in .env or environment.
    exit /b 1
)

echo %DOCKER_ACCESS_TOKEN% | docker login -u %DOCKER_USERNAME% --password-stdin
if %errorlevel% neq 0 (
    echo [ERROR] Docker authentication failed.
    exit /b 1
)

:: Network
docker network inspect %NETWORK_NAME% >nul 2>&1
if %errorlevel% neq 0 (
    echo Creating network %NETWORK_NAME%...
    docker network create %NETWORK_NAME%
)

:: Volumes
docker volume inspect %REDIS_VOLUME_NAME% >nul 2>&1 || docker volume create %REDIS_VOLUME_NAME%
docker volume inspect %KAFKA_DATA_VOLUME_NAME% >nul 2>&1 || docker volume create %KAFKA_DATA_VOLUME_NAME%
docker volume inspect %KAFKA_SECRETS_VOLUME_NAME% >nul 2>&1 || docker volume create %KAFKA_SECRETS_VOLUME_NAME%
docker volume inspect %MONGO_VOLUME_NAME% >nul 2>&1 || docker volume create %MONGO_VOLUME_NAME%

:: Redis
docker inspect %REDIS_CONTAINER_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo Redis container exists. Checking status...
    docker ps -q -f name=%REDIS_CONTAINER_NAME% >nul 2>&1
    if %errorlevel% neq 0 (
        echo Starting existing Redis...
        docker start %REDIS_CONTAINER_NAME%
    ) else (
        echo Redis is already running.
    )
) else (
    echo Starting new Redis container...
    docker run -d ^
      --name %REDIS_CONTAINER_NAME% ^
      --network %NETWORK_NAME% ^
      --restart unless-stopped ^
      -p 6379:6379 ^
      -v %REDIS_VOLUME_NAME%:/data ^
      %REDIS_IMAGE%
)

:: Kafka
docker inspect %KAFKA_CONTAINER_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo Kafka container exists. Checking status...
    docker ps -q -f name=%KAFKA_CONTAINER_NAME% >nul 2>&1
    if %errorlevel% neq 0 (
        echo Starting existing Kafka...
        docker start %KAFKA_CONTAINER_NAME%
    ) else (
        echo Kafka is already running.
    )
) else (
    echo Starting new Kafka container...
    docker run -d ^
      --name %KAFKA_CONTAINER_NAME% ^
      --network %NETWORK_NAME% ^
      -p 9092:9092 -p 29092:29092 ^
      -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093,PLAINTEXT_HOST://:29092 ^
      -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT ^
      -e KAFKA_BROKER_ID=1 ^
      -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://%KAFKA_CONTAINER_NAME%:9092,PLAINTEXT_HOST://localhost:29092 ^
      -e KAFKA_PROCESS_ROLES=broker,controller ^
      -e CLUSTER_ID=MkU3OEV5NURaZWdSMXVwMWd2V2h4dw== ^
      -e KAFKA_NODE_ID=1 ^
      -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT ^
      -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER ^
      -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@%KAFKA_CONTAINER_NAME%:9093 ^
      -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 ^
      -u appuser ^
      --restart unless-stopped ^
      -v %KAFKA_DATA_VOLUME_NAME%:/var/lib/kafka/data ^
      -v %KAFKA_SECRETS_VOLUME_NAME%:/etc/kafka/secrets ^
      %KAFKA_IMAGE%
)

:: MongoDB
docker inspect %MONGO_CONTAINER_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo MongoDB container exists. Checking status...
    docker ps -q -f name=%MONGO_CONTAINER_NAME% >nul 2>&1
    if %errorlevel% neq 0 (
        echo Starting existing MongoDB...
        docker start %MONGO_CONTAINER_NAME%
    ) else (
        echo MongoDB is already running.
    )
) else (
    echo Starting new MongoDB container...
    docker run -d ^
      --name %MONGO_CONTAINER_NAME% ^
      --network %NETWORK_NAME% ^
      --restart unless-stopped ^
      -p 27017:27017 ^
      -v %MONGO_VOLUME_NAME%:/data/db ^
      %MONGO_IMAGE%
)

echo.
echo --- Setting up Dependencies (Poetry) ---

poetry --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Poetry not found. Installing via pip...
    pip install poetry
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install Poetry. Please install manually.
    )
)

poetry --version >nul 2>&1
if %errorlevel% equ 0 (
    echo Installing project dependencies...
    poetry install
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install dependencies.
    ) else (
        echo Dependencies installed successfully.
    )
)

echo.
echo --- Environment Setup Complete ---
pause