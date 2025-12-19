# Performance Optimization

Universal AI Gateway implements several architectural strategies to maximize throughput and minimize latency/cost.

## ⚡ Smart Caching Architecture

Caching is implemented differently depending on the provider's capabilities.

### 1. Native Context Caching (Google Gemini)
**Mechanism:** Utilizes Google's `cachedContent` API.
*   **How it works:** The system hashes the `System Prompt` + `Conversation History` (excluding the last message).
*   **Storage:** If a cache miss occurs, the system creates a cache resource on Google's servers (TTL 1 hour) and stores the Resource ID in Redis.
*   **Benefit:** Massive cost reduction for long contexts. You only pay for the "diff" (the new message).

### 2. Prefix Caching (Mistral & Generic)
**Mechanism:** Implicit "Prompt Engineering" for KV-Cache hits.
*   **How it works:** Providers like Mistral and Groq automatically cache the "Prefix" (the beginning) of a prompt if it remains identical across requests.
*   **Implementation:** The Engine splits the prompt into:
    *   **Static System:** Contains immutable instructions (e.g., "You are a helpful assistant"). This is sent first.
    *   **Dynamic Context:** User location, current time, and tools are injected into the *User Message*, not the System Prompt.
*   **Benefit:** This ensures the first ~1000 tokens (the System Prompt) remain byte-for-byte identical, triggering the provider's internal cache.

---

## 🖼️ The Dual Media Pipeline (Art Studio Assets)

Handling images efficiently is critical for Vision Agents and the Art Studio pipeline.

### Pipeline A: The Gemini Way
**Flow:** `Base64 Image` -> `Redis Hash Check` -> `Google File API`
1.  Hashes the image content.
2.  Checks Redis for an existing `fileUri`.
3.  If missing, uploads directly to Google's File API.
4.  Caches the `fileUri` for 47 hours (matching Google's 48h limit).
5.  **Why:** Google Gemini creates errors or huge latency with Base64 inline data. The File API is the only stable method.

### Pipeline B: The Standard Way (OpenAI/Mistral)
**Flow:** `Base64 Image` -> `Redis Hash Check` -> `Cloudinary` -> `Public URL`
1.  Hashes the image content.
2.  Checks Redis for an existing Cloudinary URL.
3.  If missing, uploads to Cloudinary.
4.  Passes the *Public URL* to the LLM.
5.  **Why:** Most OpenAI-compatible providers (Mistral, Groq) prefer URLs over massive Base64 payloads, which eat up context tokens and bandwidth.

---

## ⚖️ Cognitive Load Balancing

Choosing the right reasoning pattern impacts both latency and quality.

| Pattern | Latency | Tokens | Best For |
| :--- | :--- | :--- | :--- |
| **Simple ReAct** | Low | Low | Fast actions, simple tool use. |
| **Sonata** | Medium | Medium | General problem solving. |
| **Cognitive Ladder** | High | High (12+ steps) | Deep analysis, creative writing, "Art Studio" planning. |

**Recommendation:**
Use `simple_react` for interactive chat. Switch to `linear_react` (Cognitive Ladder) only when you need the agent to perform deep architectural planning or creative work where latency is acceptable.

---

## 🏎️ Parallel Tool Execution

The system supports `parallel_tool_calls` where available (e.g., Llama 3.1 on Groq).
*   **Configuration:** The Engine checks the model's capabilities (defined in `*_models.py`).
*   **Optimization:** If a model supports it, the system allows it to fire multiple searches or calculations in a single turn, reducing the number of round-trips.
*   **Safety:** For models known to fail with parallel calls (e.g., older `gpt-oss` variants), this feature is explicitly stripped from the request to prevent 400 errors.
