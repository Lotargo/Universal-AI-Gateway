#!/bin/bash
cd "$(dirname "$0")"
echo "[INFO] Запуск скрипта настройки Open WebUI..."

echo "[INFO] Проверка статуса Docker..."
if ! docker info > /dev/null 2>&1; then
    echo "[ERROR] Docker не запущен или не установлен!"
    exit 1
fi
echo "[INFO] Docker активен."

echo "[INFO] Скачивание необходимых образов (docker-compose pull)..."
docker-compose -f docker-compose.yml pull
if [ $? -ne 0 ]; then
    echo "[ERROR] Ошибка при скачивании образов."
    exit 1
fi

echo "[SUCCESS] Настройка успешно завершена. Образы загружены."
echo "[INFO] Теперь вы можете запустить клиент с помощью './run_ui.sh'."
