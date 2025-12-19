@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [INFO] Запуск Open WebUI Test Client...

echo [INFO] Проверка статуса Docker...
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker не запущен! Запустите Docker Desktop.
    pause
    exit /b 1
)

echo [INFO] Запуск контейнера (docker-compose up)...
docker-compose -f docker-compose.yml up -d
if %errorlevel% neq 0 (
    echo [ERROR] Не удалось запустить контейнер. Проверьте логи выше.
    pause
    exit /b 1
)

echo [SUCCESS] Open WebUI успешно запущен!
echo [INFO] Интерфейс доступен по адресу: http://localhost:13000
pause
