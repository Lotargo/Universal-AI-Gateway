# Integration Guide: Connecting Apps to Universal AI Gateway

Universal AI Gateway provides an OpenAI-compatible API, making it easy to connect almost any AI-enabled application, IDE extension, or chat client.

## 1. Prerequisites

Before connecting, ensure:
*   The Gateway server is running.
*   You know the server's address (e.g., `http://localhost:8001` or your public domain).

## 2. Authentication (Getting an API Key)

By default, the Gateway requires authentication. You need to obtain a Bearer token (API Key) by registering a user.

### Step 1: Register
Send a POST request to `/v1/auth/register`:

**Using curl:**
```bash
curl -X POST "http://localhost:8001/v1/auth/register" \
     -H "Content-Type: application/json" \
     -d '{"username": "myuser", "password": "mypassword"}'
```

**Response:**
```json
{
  "username": "myuser",
  "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
  "token_type": "bearer"
}
```
The `access_token` string is your **API Key**.

---

## 3. Configuration Parameters

Use these settings in your third-party application:

| Setting | Value | Notes |
| :--- | :--- | :--- |
| **API Base URL** | `http://<host>:8001/v1` | **Important:** Must end with `/v1`. Some apps auto-append this, others don't. Try removing `/v1` if it fails. |
| **API Key** | `<your_access_token>` | The token you got from step 2. |
| **Model Name** | (See below) | You can fetch the list or use an alias like `google-gemini-2.0-flash`. |

---

## 4. Listing Available Models

To see which models are available for use (including specialized Agent modes), call the standard OpenAI models endpoint.

**Endpoint:** `GET /v1/models`

**Using curl:**
```bash
curl "http://localhost:8001/v1/models" \
     -H "Authorization: Bearer <your_access_token>"
```

**Response Example:**
```json
{
  "object": "list",
  "data": [
    {"id": "google-standard-chat", "object": "model", ...},
    {"id": "mistral-deep-thought", "object": "model", ...},
    {"id": "groq-analytical-react", "object": "model", ...}
  ]
}
```

---

## 5. Usage Examples

### Python (using `openai` library)

The Gateway is fully compatible with the official OpenAI Python client.

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8001/v1",
    api_key="<your_access_token>"
)

# 1. List Models
models = client.models.list()
print(f"Available models: {[m.id for m in models]}")

# 2. Chat Completion
response = client.chat.completions.create(
    model="google-standard-chat",
    messages=[
        {"role": "user", "content": "Hello! How does the Gateway work?"}
    ]
)

print(response.choices[0].message.content)
```

### Generic App Configuration (e.g., LibreChat, Cursor)

Most apps have a "Custom OpenAI" or "OpenAI Compatible" section.

1.  **Enable Custom Endpoint:** Check the box or toggle.
2.  **Base URL:** Enter `http://localhost:8001/v1` (or your server IP).
3.  **API Key:** Paste your `access_token`.
4.  **Model:** Manually type the model ID (e.g., `google-deep-thought`) if the dropdown doesn't populate automatically.

---

## 6. Troubleshooting

*   **401 Unauthorized:** Your token is invalid or missing. Re-register or check the header.
*   **404 Not Found:** Check your Base URL. Did you forget `/v1`? Or did you add it twice (`/v1/v1`)?
*   **429 Too Many Requests:** You hit the rate limit (60 req/min). Wait a moment.
