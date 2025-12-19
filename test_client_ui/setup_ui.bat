@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo [INFO] Запуск скрипта настройки Open WebUI...

echo [INFO] Проверка статуса Docker...
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker не запущен или не установлен! Пожалуйста, запустите Docker Desktop.
    echo [HINT] Попробуйте выполнить команду 'docker info' в терминале вручную.
    pause
    exit /b 1
)
echo [INFO] Docker активен.

echo [INFO] Скачивание необходимых образов (docker-compose pull)...
docker-compose -f docker-compose.yml pull
if %errorlevel% neq 0 (
    echo [ERROR] Ошибка при скачивании образов.
    echo [HINT] Проверьте интернет-соединение или настройки VPN.
    pause
    exit /b 1
)

echo [SUCCESS] Настройка успешно завершена. Образы загружены.
echo [INFO] Теперь вы можете запустить клиент с помощью 'run_ui.bat'.
pause
