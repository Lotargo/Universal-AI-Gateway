#!/bin/bash
set -e

echo "=== Universal AI Gateway CI Pipeline ==="

echo "1. Installing Dependencies..."
poetry install

echo "2. Starting Server in Mock Mode..."
export MOCK_MODE=true
export PYTHONPATH=.
# Using 4 workers to match production/load test config
# We capture PID to kill it later
poetry run uvicorn main:app --host 0.0.0.0 --port 8001 --workers 4 > server.log 2>&1 &
SERVER_PID=$!
echo "Server started with PID $SERVER_PID"

# Wait for server to be ready
echo "Waiting for server to startup..."
sleep 10

# Check if server is running
if ! kill -0 $SERVER_PID > /dev/null 2>&1; then
    echo "Server failed to start!"
    cat server.log
    exit 1
fi

echo "3. Running Locust Stress Test..."
# Run StressUser only
# Explicitly specifying StressUser class to avoid errors with other classes not having matching tags
poetry run locust -f tests/performance/locustfile.py StressUser --headless -u 5 -r 1 --run-time 10s --host http://localhost:8001

LOCUST_EXIT_CODE=$?

echo "4. Cleaning up..."
kill $SERVER_PID || true
rm -f server.log

if [ $LOCUST_EXIT_CODE -eq 0 ]; then
    echo "✅ CI Pipeline Passed!"
    exit 0
else
    echo "❌ CI Pipeline Failed!"
    exit 1
fi
