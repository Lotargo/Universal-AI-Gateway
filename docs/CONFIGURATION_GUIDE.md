# Configuration Guide

Universal AI Gateway utilizes a unique **Python-based DSL (Domain Specific Language)** for configuration. This approach offers superior flexibility compared to static YAML or JSON files, allowing for dynamic logic, inheritance, and automatic mutation of agent behaviors.

> **Developer Note:** For a deep technical dive into the internal workings of the DSL engine (loaders, schema enforcement, mutations), please refer to the [DSL Reference Guide](./DSL_REFERENCE.md).

## 📂 Directory Structure

All configurations reside in `core/config/`:

*   `core/config/agents/`: **Agent Definitions** (`*_agent.py`).
*   `core/config/base/`: **Model & Tier Definitions** (`*_models.py`).
*   `core/config/default_config.py`: **The Engine** (Loads and processes the configs).

---

## 🤖 Defining an Agent

To create a new agent, simply add a Python file ending in `_agent.py` to `core/config/agents/`. The system will automatically discover it.

**File:** `core/config/agents/my_agent.py`

```python
AGENT_CONFIG = {
    # 1. Identity
    "name": "my-custom-agent",
    "description": "An agent specialized in creative writing.",
    "aliases": ["writer", "poet"],

    # 2. System Prompt
    "system_instruction": (
        "You are a creative writing assistant. "
        "Always use metaphors and vivid imagery."
    ),

    # 3. Model Parameters
    "settings": {
        "temperature": 0.9,
        "top_p": 0.95,
        "agent_settings": {
            # Defines the cognitive architecture
            "reasoning_mode": "linear_react",
            "output_format": "text"
        }
    },

    # 4. Routing Strategy (The Chain)
    "router_config": {
        "main": ["claude_tier_1", "gpt_tier_1"], # Primary pool
        "fallbacks": ["mistral_large"]           # Used if primary fails
    }
}
```

### Key Parameters
*   `reasoning_mode`: Determines the cognitive pattern.
    *   `simple_react`: Standard ReAct (Tools + Actions).
    *   `linear_react`: Cognitive Ladder (12-step Deep Reasoning).
    *   `analytical_react`: Reflexion (Draft -> Critique -> Refine).
    *   `sonata_react`: Structured Synthesis (Analysis -> Strategy).
*   `router_config`: Defines the failover chain. You can reference specific models (e.g., `gemini-1.5-pro`) or abstract Tiers (e.g., `vision_tier_1`).

---

## 🎨 Configuring "Art Studio" Agents

The ecosystem includes specialized agents for media creation. These require specific setups.

### Vision Agent
Defined in `core/config/agents/vision_agent.py`.
*   **Purpose:** Analyzing images and generating descriptions for the Art Studio pipeline.
*   **Requirement:** Requires a model from `VISION_TIERS` (Tier 1 is recommended for detailed analysis).
*   **Media Pipeline:** Automatically handles image uploads via the Dual Media Pipeline (see [Performance Optimization](./PERFORMANCE_OPTIMIZATION.md)).

### Coding Agent
Defined in `core/config/agents/coding_agent.py`.
*   **Purpose:** Autonomous code generation (The "Jules" equivalent).
*   **Best Practice:** Set `reasoning_mode` to `analytical_react` to force the agent to critique its own code before finalizing it.

---

## 📦 Defining Models & Tiers

Models are grouped into "Tiers" to facilitate load balancing and abstraction. These are defined in `core/config/base/`.

**File:** `core/config/base/vision_models.py`

```python
# Defines a Tier (Pool of models)
VISION_TIERS = {
    "vision_tier_1": [
        "gemini-2.0-flash",
        "gpt-4o",
        "claude-3-opus"
    ],
    "vision_tier_2": [
        "gemini-1.5-flash",
        "mistral-large"
    ]
}
```

*   **Tiers (`*_TIERS`):** A list of model aliases. The system uses Round-Robin rotation to select a model from the list for each request.
*   **Zero-Config Loading:** Any dict ending in `_TIERS` in any file ending in `_models.py` is automatically registered.

---

## 🔄 The Rotation Engine

The configuration system works in tandem with the `RotationManager` to ensure high availability.

1.  **Request:** User asks for `my-custom-agent`.
2.  **Resolution:** The system looks up `router_config["main"]`.
3.  **Expansion:**
    *   If the entry is a **Tier** (e.g., `vision_tier_1`), it expands into `[gemini-2.0, gpt-4o, ...]`.
    *   It selects one model based on the global Round-Robin index.
4.  **Key Selection:** Once a concrete model (e.g., `google/gemini-2.0`) is chosen, the `ApiKeyManager` provides a rotated key for that specific provider.
5.  **Fallback:** If the request fails (and isn't recovered), the system moves to `router_config["fallbacks"]`.

---

## ⚙️ Environment Variables

Managed via the `.env` file.

| Variable | Description | Default |
| :--- | :--- | :--- |
| `AUTH_ENABLED` | Enable token-based authentication. | `True` |
| `ADMIN_TOKEN` | Master token for admin routes. | - |
| `REDIS_HOST` | Hostname for Redis. | `localhost` |
| `KAFKA_BROKER` | Address for Kafka. | `localhost:29092` |
| `CLOUDINARY_URL`| Connection string for image storage. | - |
| `GOOGLE_SEARCH_CX`| Google Custom Search Engine ID. | - |

---

## 🧬 Automatic Mutations

One of the most powerful features of the DSL is **Mutations**.
When you define `my-custom-agent`, the system automatically generates variations based on available ReAct patterns:

*   `my-custom-agent` (Standard, inherits base reasoning)
*   `my-custom-agent_linear` (Linear Cognitive Ladder - Deep Planning)
*   `my-custom-agent_sonata` (Sonata Pattern - Balanced Strategy)
*   `my-custom-agent_analytical` (Reflexion - Self-Correction)

This allows you to switch reasoning strategies on the fly without changing the agent's core definition. For example, use `_linear` when you need the agent to think deeply about a plan before executing it.
