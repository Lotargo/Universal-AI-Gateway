#!/bin/bash
# run/run_server.sh

echo "Starting Universal AI Gateway server..."
echo ""
echo "Server will be available at:"
echo "  - Dashboard/Registration: http://localhost:8001"
echo "  - Swagger UI:            http://localhost:8001/docs"
echo ""

# SSL Configuration (Optional)
# To enable SSL, set the environment variables:
# SSL_KEYFILE=/path/to/key.pem
# SSL_CERTFILE=/path/to/cert.pem

# Add the project root to the PYTHONPATH to ensure modules are found
export PYTHONPATH=$PYTHONPATH:.

# Construct command args
CMD_ARGS="main:app --host 0.0.0.0 --port 8001 --workers 4"

if [ -n "$SSL_KEYFILE" ] && [ -n "$SSL_CERTFILE" ]; then
    echo "🔐 SSL Enabled."
    CMD_ARGS="$CMD_ARGS --ssl-keyfile $SSL_KEYFILE --ssl-certfile $SSL_CERTFILE"
else
    echo "🔓 SSL Disabled (running in HTTP mode)."
fi

# Install dependencies first (in case environment was recreated)
echo "Installing dependencies..."
poetry lock || { echo "❌ Failed to lock dependencies"; exit 1; }
poetry install --no-root || { echo "❌ Failed to install dependencies"; exit 1; }

# Run the server using poetry to ensure the correct environment
poetry run uvicorn $CMD_ARGS
