#!/bin/bash
set -e

export MOCK_MODE=true
export AUTH_ENABLED=True
export AUTH_SECRET=secret123
export PYTHONPATH=.

# Clean previous
rm -f load_test_kafka.log server.log
rm -f tests/performance/results_*.csv

# Ensure Kafka is ready (simple restart to clear state/connection issues)
echo "Restarting Kafka..."
sudo docker restart shared-kafka
sleep 15

echo "Creating Kafka Topic..."
sudo docker exec shared-kafka kafka-topics --create --topic agent_audit_events --bootstrap-server kafka:9092 --partitions 1 --replication-factor 1 --if-not-exists

echo "[1/4] Starting Kafka Monitor..."
poetry run python -u tests/performance/kafka_monitor.py > load_test_kafka.log 2>&1 &
MONITOR_PID=$!

echo "[2/4] Starting Server (Mock Mode + Auth) on Port 8001..."
# We run uvicorn via python main.py
poetry run python main.py > server.log 2>&1 &
SERVER_PID=$!

echo "Waiting 20s for server startup..."
sleep 20

# Check if server is up
if ! kill -0 $SERVER_PID 2>/dev/null; then
    echo "Server failed to start. Check server.log"
    cat server.log
    kill $MONITOR_PID
    exit 1
fi

echo "[3/4] Running Locust Load Test..."
# Target Port 8001
poetry run locust -f tests/performance/locustfile.py \
    --headless \
    -u 10 -r 2 \
    --run-time 30s \
    --host http://localhost:8001 \
    --csv=tests/performance/results

echo "[4/4] Finishing..."
kill $SERVER_PID
kill $MONITOR_PID

echo "--- Kafka Monitor Log ---"
cat load_test_kafka.log
echo "-------------------------"

echo "--- Locust Results (Head) ---"
head -n 5 tests/performance/results_stats.csv
