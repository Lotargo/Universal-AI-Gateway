#!/bin/bash
cd "$(dirname "$0")"
echo "[INFO] Запуск Open WebUI Test Client..."

echo "[INFO] Проверка статуса Docker..."
if ! docker info > /dev/null 2>&1; then
    echo "[ERROR] Docker не запущен! Пожалуйста, запустите Docker."
    exit 1
fi

echo "[INFO] Запуск контейнера (docker-compose up)..."
docker-compose -f docker-compose.yml up -d
if [ $? -ne 0 ]; then
    echo "[ERROR] Не удалось запустить контейнер."
    exit 1
fi

echo "[SUCCESS] Open WebUI успешно запущен!"
echo "[INFO] Интерфейс доступен по адресу: http://localhost:13000"
