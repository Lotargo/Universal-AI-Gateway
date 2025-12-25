#!/bin/bash

# ===================================================================================
# SCRIPT FOR REPRODUCING INFRASTRUCTURE AND TESTING (docker-compose configuration)
# ===================================================================================

# --- Colors ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}--- STARTING REPRODUCTION SETUP ---${NC}"

# --- 1. CLEANUP ---
echo -e "${YELLOW}1. Cleaning up existing environment...${NC}"
CONTAINERS="shared-redis shared-kafka shared-mongo magic-redis magic-kafka magic-mongo magic-app"
for container in $CONTAINERS; do
    if sudo docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "Removing container: $container"
        sudo docker rm -f $container
    fi
done

# Clean up volumes for a fresh start (Crucial for Kafka Cluster ID mismatch)
VOLUMES="mongo_data redis_data kafka_data"
for volume in $VOLUMES; do
    if sudo docker volume ls -q | grep -q "^${volume}$"; then
         echo "Removing volume: $volume"
         sudo docker volume rm $volume
    fi
done

# Also kill any running uvicorn instance on port 8001
PID=$(lsof -t -i :8001)
if [ ! -z "$PID" ]; then
    echo "Killing existing process on port 8001: $PID"
    kill -9 $PID
fi
echo -e "${GREEN}Cleanup complete.${NC}"

# --- 2. DOCKER AUTH ---
echo -e "${YELLOW}2. Authenticating with Docker Hub...${NC}"
USER=${DOCKER_USERNAME:}
PASS=${DOCKER_ACCESS_TOKEN:}
echo "$PASS" | sudo docker login -u "$USER" --password-stdin

# --- 3. START INFRASTRUCTURE (Matching docker-compose.yml) ---
echo -e "${YELLOW}3. Starting Infrastructure...${NC}"

# Network
sudo docker network create magic-net 2>/dev/null || true

# Redis
echo "Starting Redis (redis:7-alpine)..."
sudo docker run -d \
  --name magic-redis \
  --network magic-net \
  -p 6379:6379 \
  -v redis_data:/data \
  redis:7-alpine

# Mongo
echo "Starting Mongo (mongo:6.0)..."
sudo docker run -d \
  --name magic-mongo \
  --network magic-net \
  -p 27017:27017 \
  -v mongo_data:/data/db \
  mongo:6.0

# Kafka
echo "Starting Kafka (confluentinc/cp-kafka:7.5.0)..."
# Note: Using settings from docker-compose.yml
# Hostname must be 'kafka' for internal docker networking if other containers were used,
# but here 'localhost' mapping is key for the host app.
sudo docker run -d \
  --name magic-kafka \
  --hostname kafka \
  --network magic-net \
  -p 9092:9092 \
  -p 29092:29092 \
  -v kafka_data:/var/lib/kafka/data \
  -e KAFKA_NODE_ID=1 \
  -e KAFKA_PROCESS_ROLES='broker,controller' \
  -e KAFKA_LISTENERS='INTERNAL://0.0.0.0:29092,EXTERNAL://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093' \
  -e KAFKA_ADVERTISED_LISTENERS='INTERNAL://kafka:29092,EXTERNAL://localhost:9092' \
  -e KAFKA_CONTROLLER_QUORUM_VOTERS='1@kafka:9093' \
  -e KAFKA_LISTENER_SECURITY_PROTOCOL_MAP='CONTROLLER:PLAINTEXT,INTERNAL:PLAINTEXT,EXTERNAL:PLAINTEXT' \
  -e KAFKA_INTER_BROKER_LISTENER_NAME='INTERNAL' \
  -e KAFKA_CONTROLLER_LISTENER_NAMES='CONTROLLER' \
  -e KAFKA_LOG_DIRS='/var/lib/kafka/data' \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e CLUSTER_ID='lOeC-iPqQt2gkyX-GWy0tA' \
  confluentinc/cp-kafka:7.5.0

echo -e "${YELLOW}Waiting for Kafka to be ready (15s)...${NC}"
sleep 15

# --- 4. INSTALL DEPENDENCIES ---
echo -e "${YELLOW}4. Installing Dependencies...${NC}"
# Installing system deps if missing (best effort)
sudo apt-get update && sudo apt-get install -y build-essential libffi-dev > /dev/null 2>&1

if ! command -v poetry &> /dev/null; then
    pip install poetry
fi

# Fix lock file mismatch
echo "Updating poetry.lock..."
poetry lock

poetry install --no-root

# --- 5. RUN APP LOCALLY ---
echo -e "${YELLOW}5. Starting App Locally...${NC}"

# Set ENV vars to point to localhost ports we exposed
export REDIS_HOST=localhost
export REDIS_PORT=6379
export MONGO_URI=mongodb://localhost:27017
export KAFKA_BROKER=localhost:9092
export ENABLE_CONSOLE_TRACING=false
export ENABLE_FILE_TRACING=true

# Start Uvicorn in background and log to file
poetry run uvicorn core.api.server:app --host 0.0.0.0 --port 8001 > app_output.log 2>&1 &
APP_PID=$!
echo "App started with PID $APP_PID. Waiting for port 8001..."

# Wait for port 8001
for i in {1..30}; do
    if lsof -i :8001 > /dev/null; then
        echo -e "${GREEN}App is listening on 8001!${NC}"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo -e "${RED}Timeout waiting for app to start.${NC}"
        cat app_output.log
        exit 1
    fi
done

# --- 6. TEST REQUEST ---
echo -e "${YELLOW}6. Sending Test Request (Standard Agent)...${NC}"
sleep 5 # Give it a slight moment to initialize internal components

# Send request
RESPONSE=$(curl -s -X POST http://localhost:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "standard",
    "messages": [
      {"role": "user", "content": "Привет! Это тест Kafka."}
    ]
  }')

echo -e "\n${GREEN}Response received:${NC}"
echo "$RESPONSE"

echo -e "\n${YELLOW}--- APP LOGS (Last 20 lines) ---${NC}"
tail -n 20 app_output.log

# Check if response contains "content" (basic check)
if [[ "$RESPONSE" == *"content"* ]]; then
    echo -e "\n${GREEN}TEST SUCCESSFUL: Response received.${NC}"
else
    echo -e "\n${RED}TEST FAILED: Invalid response or timeout.${NC}"
fi

# Cleanup app process
kill $APP_PID
