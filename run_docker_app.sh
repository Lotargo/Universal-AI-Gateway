#!/bin/bash

# ===================================================================================
# СКРИПТ ДЛЯ ЗАПУСКА ПРИЛОЖЕНИЯ В DOCKER (LINUX/MACOS)
# ===================================================================================
# Описание:
# Сборка и запуск контейнера приложения (magic-proxy-app).
# ===================================================================================

echo -e "\n--- Universal AI Gateway Docker Launcher ---"

# Конфигурация
APP_IMAGE_NAME="magic-proxy-app"
APP_CONTAINER_NAME="magic-proxy-app"
NETWORK_NAME="magpr1_shared_infra_net"

# Цвета
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# 1. Проверка Docker
if ! [ -x "$(command -v docker)" ]; then
    echo -e "${RED}[ERROR] Docker не установлен или не в PATH.${NC}"
    exit 1
fi

# 2. Проверка сети (должна быть создана через setup_infra.sh)
if ! docker network inspect $NETWORK_NAME >/dev/null 2>&1; then
    echo -e "${YELLOW}[WARNING] Сеть '$NETWORK_NAME' не найдена!${NC}"
    echo "Пожалуйста, запустите './setup_infra.sh' для инициализации инфраструктуры."
    exit 1
fi

echo -e "\n${GREEN}--- Сборка образа приложения ---${NC}"
docker build -t $APP_IMAGE_NAME .
if [ $? -ne 0 ]; then
    echo -e "${RED}[ERROR] Сборка Docker образа не удалась.${NC}"
    exit 1
fi

echo -e "\n${YELLOW}--- Остановка предыдущего контейнера ---${NC}"
docker stop $APP_CONTAINER_NAME >/dev/null 2>&1
docker rm $APP_CONTAINER_NAME >/dev/null 2>&1

echo -e "\n${GREEN}--- Запуск контейнера приложения ---${NC}"
echo "Конфигурация:"
echo "  - Network: $NETWORK_NAME"
echo "  - Ports:   8001:8001"
echo "  - Volume:  $(pwd) -> /app"
echo "  - Redis:   shared-redis"
echo "  - Kafka:   shared-kafka:9092"
echo "  - Mongo:   shared-mongo:27017"
echo ""

# Запуск в foreground, чтобы видеть логи
docker run \
  --name $APP_CONTAINER_NAME \
  --network $NETWORK_NAME \
  -p 8001:8001 \
  -e REDIS_HOST=shared-redis \
  -e KAFKA_BROKER=shared-kafka:9092 \
  -e MONGO_URL=mongodb://shared-mongo:27017 \
  -v "$(pwd)":/app \
  $APP_IMAGE_NAME

if [ $? -ne 0 ]; then
    echo -e "\n${RED}[ERROR] Контейнер завершил работу с ошибкой.${NC}"
fi
