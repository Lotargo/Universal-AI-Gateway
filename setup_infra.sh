#!/bin/bash

# ===================================================================================
# СКРИПТ ДЛЯ РАЗВЕРТЫВАНИЯ ИНФРАСТРУКТУРЫ (REDIS + KAFKA + MONGO)
# ===================================================================================
# Описание:
# Этот скрипт подготавливает рабочее окружение.
# Исправления v3:
# - Возвращено использование sudo для всех команд Docker.
# - Явная аутентификация через sudo docker login для root.
# ===================================================================================

# --- КОНФИГУРАЦИЯ СЕРВИСОВ ---
NETWORK_NAME="magpr1_shared_infra_net"
REDIS_CONTAINER_NAME="shared-redis"
KAFKA_CONTAINER_NAME="shared-kafka"
MONGO_CONTAINER_NAME="shared-mongo"

REDIS_VOLUME_NAME="redis-data"
KAFKA_DATA_VOLUME_NAME="kafka-data"
KAFKA_SECRETS_VOLUME_NAME="kafka-secrets"
MONGO_VOLUME_NAME="mongo-data"

REDIS_IMAGE="redis:7-alpine"
KAFKA_IMAGE="confluentinc/cp-kafka:latest"
MONGO_IMAGE="mongo:latest"

# --- Цвета для вывода ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}--- Начало подготовки окружения ---${NC}"

# --- БЛОК 1: ПРОВЕРКА DOCKER ---
echo -e "${GREEN}1. Проверка установки Docker...${NC}"
if ! [ -x "$(command -v docker)" ]; then
    echo -e "${RED}Ошибка: Docker не установлен. Установка прервана.${NC}"
    exit 1
fi
echo -e "${GREEN}Docker найден.${NC}"


# --- БЛОК 2: АУТЕНТИФИКАЦИЯ В DOCKER HUB ---
echo -e "${GREEN}2. Аутентификация в Docker Hub (root)...${NC}"

# Load .env file if exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check for environment variables
if [ -z "$DOCKER_USERNAME" ] || [ -z "$DOCKER_ACCESS_TOKEN" ]; then
    echo -e "${RED}Ошибка: Переменные DOCKER_USERNAME и DOCKER_ACCESS_TOKEN не найдены в .env или окружении.${NC}"
    echo -e "${YELLOW}Пожалуйста, добавьте их в файл .env в корне проекта.${NC}"
    exit 1
fi

# Важно: логинимся через sudo, чтобы креды сохранились для root
echo "$DOCKER_ACCESS_TOKEN" | sudo docker login -u "$DOCKER_USERNAME" --password-stdin
if [ $? -ne 0 ]; then
    echo -e "${RED}Ошибка аутентификации в Docker Hub.${NC}"
    exit 1
else
    echo -e "${GREEN}Аутентификация прошла успешно.${NC}"
fi


# --- БЛОК 3: ПОДГОТОВКА ИНФРАСТРУКТУРЫ DOCKER ---
echo -e "${GREEN}3. Подготовка сети и томов Docker...${NC}"
sudo docker network inspect $NETWORK_NAME >/dev/null 2>&1 || sudo docker network create $NETWORK_NAME
sudo docker volume inspect $REDIS_VOLUME_NAME >/dev/null 2>&1 || sudo docker volume create $REDIS_VOLUME_NAME
sudo docker volume inspect $KAFKA_DATA_VOLUME_NAME >/dev/null 2>&1 || sudo docker volume create $KAFKA_DATA_VOLUME_NAME
sudo docker volume inspect $KAFKA_SECRETS_VOLUME_NAME >/dev/null 2>&1 || sudo docker volume create $KAFKA_SECRETS_VOLUME_NAME
sudo docker volume inspect $MONGO_VOLUME_NAME >/dev/null 2>&1 || sudo docker volume create $MONGO_VOLUME_NAME
echo -e "${GREEN}Сеть и тома готовы.${NC}"


# --- БЛОК 4: ЗАПУСК СЕРВИСОВ ---
echo -e "${GREEN}4. Запуск и проверка сервисов...${NC}"

# 4.1. Redis
echo -e "${YELLOW}Проверка статуса контейнера Redis ($REDIS_CONTAINER_NAME)...${NC}"
if [ "$(sudo docker inspect -f '{{.State.Running}}' $REDIS_CONTAINER_NAME 2>/dev/null)" == "true" ]; then
    echo -e "${GREEN}Redis уже запущен.${NC}"
else
    if [ "$(sudo docker ps -aq -f name=$REDIS_CONTAINER_NAME)" ]; then
        echo -e "${YELLOW}Удаление остановленного контейнера Redis...${NC}"
        sudo docker rm $REDIS_CONTAINER_NAME
    fi
    echo -e "${YELLOW}Запуск контейнера Redis...${NC}"
    sudo docker run -d \
      --name $REDIS_CONTAINER_NAME \
      --network $NETWORK_NAME \
      --restart unless-stopped \
      -p 6379:6379 \
      -v $REDIS_VOLUME_NAME:/data \
      $REDIS_IMAGE
    if [ $? -ne 0 ]; then echo -e "${RED}Ошибка при запуске Redis!${NC}"; exit 1; fi
    sleep 3
    echo -e "${GREEN}Контейнер Redis успешно запущен.${NC}"
fi

# 4.2. Kafka
echo -e "${YELLOW}Проверка статуса контейнера Kafka ($KAFKA_CONTAINER_NAME)...${NC}"
if [ "$(sudo docker inspect -f '{{.State.Running}}' $KAFKA_CONTAINER_NAME 2>/dev/null)" == "true" ]; then
    echo -e "${GREEN}Kafka уже запущен.${NC}"
else
    if [ "$(sudo docker ps -aq -f name=$KAFKA_CONTAINER_NAME)" ]; then
        echo -e "${YELLOW}Удаление остановленного контейнера Kafka...${NC}"
        sudo docker rm $KAFKA_CONTAINER_NAME
    fi
    echo -e "${YELLOW}Запуск контейнера Kafka в режиме KRaft...${NC}"
    sudo docker run -d \
      --name $KAFKA_CONTAINER_NAME \
      --hostname kafka \
      --network $NETWORK_NAME \
      -p 9092:9092 -p 29092:29092 \
      -e KAFKA_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093,PLAINTEXT_HOST://:29092 \
      -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT \
      -e KAFKA_BROKER_ID=1 \
      -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092,PLAINTEXT_HOST://127.0.0.1:29092 \
      -e KAFKA_PROCESS_ROLES=broker,controller \
      -e CLUSTER_ID=MkU3OEV5NURaZWdSMXVwMWd2V2h4dw== \
      -e KAFKA_NODE_ID=1 \
      -e KAFKA_INTER_BROKER_LISTENER_NAME=PLAINTEXT \
      -e KAFKA_CONTROLLER_LISTENER_NAMES=CONTROLLER \
      -e KAFKA_CONTROLLER_QUORUM_VOTERS=1@kafka:9093 \
      -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
      -u appuser \
      --restart unless-stopped \
      -v $KAFKA_DATA_VOLUME_NAME:/var/lib/kafka/data \
      -v $KAFKA_SECRETS_VOLUME_NAME:/etc/kafka/secrets \
      $KAFKA_IMAGE
    if [ $? -ne 0 ]; then echo -e "${RED}Ошибка при запуске Kafka!${NC}"; exit 1; fi
    echo -e "${YELLOW}Ожидание стабилизации Kafka (10 секунд)...${NC}"
    sleep 10
    echo -e "${GREEN}Контейнер Kafka успешно запущен.${NC}"
fi

# 4.3. MongoDB
echo -e "${YELLOW}Проверка статуса контейнера MongoDB ($MONGO_CONTAINER_NAME)...${NC}"
if [ "$(sudo docker inspect -f '{{.State.Running}}' $MONGO_CONTAINER_NAME 2>/dev/null)" == "true" ]; then
    echo -e "${GREEN}MongoDB уже запущен.${NC}"
else
    if [ "$(sudo docker ps -aq -f name=$MONGO_CONTAINER_NAME)" ]; then
        echo -e "${YELLOW}Удаление остановленного контейнера MongoDB...${NC}"
        sudo docker rm $MONGO_CONTAINER_NAME
    fi
    echo -e "${YELLOW}Запуск контейнера MongoDB...${NC}"
    sudo docker run -d \
      --name $MONGO_CONTAINER_NAME \
      --network $NETWORK_NAME \
      --restart unless-stopped \
      -p 27017:27017 \
      -v $MONGO_VOLUME_NAME:/data/db \
      $MONGO_IMAGE
    if [ $? -ne 0 ]; then echo -e "${RED}Ошибка при запуске MongoDB!${NC}"; exit 1; fi
    sleep 3
    echo -e "${GREEN}Контейнер MongoDB успешно запущен.${NC}"
fi

# --- БЛОК 5: УСТАНОВКА ЗАВИСИМОСТЕЙ (POETRY) ---
echo -e "${GREEN}5. Установка и настройка Poetry...${NC}"
if ! command -v poetry &> /dev/null; then
    echo -e "${YELLOW}Poetry не найден. Установка через pip...${NC}"
    pip install poetry
    if [ $? -ne 0 ]; then
        echo -e "${RED}Ошибка при установке Poetry. Проверьте pip.${NC}"
        # Не выходим, так как инфраструктура уже поднята, но предупреждаем
    fi
else
    echo -e "${GREEN}Poetry уже установлен.$(poetry --version)${NC}"
fi

if command -v poetry &> /dev/null; then
    echo -e "${YELLOW}Установка зависимостей проекта...${NC}"
    poetry install
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Зависимости успешно установлены.${NC}"
    else
        echo -e "${RED}Ошибка при установке зависимостей через Poetry.${NC}"
    fi
fi

echo -e "\n${GREEN}--- Окружение успешно подготовлено ---${NC}"
echo -e "${GREEN}Все необходимые сервисы (Redis, Kafka, MongoDB) запущены, зависимости установлены.${NC}"
