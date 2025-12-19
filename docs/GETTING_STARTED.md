# Getting Started

This guide will help you set up **Universal AI Gateway** on your local machine. The system is designed to be run as a containerized **AI Ecosystem** (Art Studio).

## 📋 Prerequisites

Before you begin, ensure you have the following installed:
*   **Docker & Docker Compose:** The core runtime environment.
*   **Git:** To clone the repository.
*   *(Optional)* **Python 3.10+ & Poetry:** If you plan to run the system without Docker for development.

### Hardware Requirements
*   **CPU:** 2+ Cores recommended.
*   **RAM:** 4GB+ (mostly for the containers; the Python app is lightweight).
*   **Disk:** ~5GB for Docker images and logs.

---

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone <repository-url>
cd universal-ai-gateway
```

### 2. Configure Environment Variables
The system relies on a `.env` file in the root directory. Copy the example or create a new one:

```bash
# .env example
AUTH_ENABLED=True
ADMIN_TOKEN=super-secret-admin-token

# Critical Infrastructure
REDIS_HOST=redis
REDIS_PORT=6379
KAFKA_BROKER=kafka:9092

# Media Pipeline (Art Studio)
# Required for non-Google vision models to "see" images
CLOUDINARY_URL=cloudinary://key:secret@cloud_name
```

> **Note:** API Keys are managed separately in the `keys_pool/` directory.

### 3. Setup API Keys
Navigate to `keys_pool/` and add your provider keys. The system expects files named `provider_tier.env` (e.g., `google_free.env`, `groq_free.env`).
Format: One raw key per line (no `KEY=VALUE`).

```text
# keys_pool/google_free.env
AIzaSyD...
AIzaSyA...
```

### 4. Build and Run via Docker
The easiest way to start is using the provided setup script.

**Linux/macOS:**
```bash
./setup_infra.sh
```

**Windows:**
```bat
setup_infra.bat
```

This script will:
1.  Verify Docker is running.
2.  Start infrastructure containers (Redis, Kafka, Zookeeper, MongoDB).
3.  Build and start the Gateway backend.

---

## 🚦 Verifying the Installation

Once the containers are running, the API will be available at `http://localhost:8001`.

### Health Check
Since there is no dedicated `/health` endpoint, you can verify the server is up by visiting the root URL in your browser:
*   **URL:** `http://localhost:8001/`
*   **Expected Result:** You should see the Gateway Registration/Dashboard page.

### Testing the Art Studio (Vision Agent)
The repository includes a sandbox environment based on **OpenWebUI** to verify the OpenAI-compatible protocol.

1.  Ensure the `test_client_ui` container is running (it is part of the `docker-compose` stack).
2.  Access the UI at `http://localhost:3000` (default port, check `docker-compose.yml` if different).
3.  Configure the connection:
    *   **Base URL:** `http://host.docker.internal:8001/v1` (or your machine's IP).
    *   **API Key:** Any valid string (if Auth is disabled) or your registered token.
4.  Select the **`vision-agent`** model.
5.  Upload an image and ask: "Describe this image in detail for a prompt."
6.  *Observation:* The system will handle the upload (via Cloudinary or Gemini File API) and return a description.

---

## 🛑 Troubleshooting

### "Kafka Producer not available"
*   **Symptom:** Logs show connection errors to Kafka, but server starts.
*   **Impact:** Agent auditing (ReAct logs) will be disabled. The agent will function, but you won't see reasoning steps in the audit stream.
*   **Fix:** Ensure the `kafka` container is healthy. Restart with `docker-compose restart kafka`.

### "Redis Connection Error"
*   **Symptom:** Error logs connecting to Redis.
*   **Impact:** **Critical.** Caching, Rate Limiting, and SSE (Streaming) will fail or degrade significantly.
*   **Fix:** Ensure Redis is running. Check `REDIS_HOST` in `.env`.

### "400 Bad Request" from Providers
*   **Symptom:** Frequent errors from Groq or Llama models.
*   **Fix:** The system has built-in "Advanced Recovery" for this. Check the logs—you should see messages like "Recovering from model error... Executing tool manually". If it persists, try using the `simple_react` pattern or switching to a more robust model (Tier 1).
