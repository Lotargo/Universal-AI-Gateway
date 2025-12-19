"""Explicit fallback sequences for general routing.

Defines the order of providers or specific models to attempt when a request fails.
These chains apply to standard chat and reasoning modes.

NOTE: Specific model tiers (Vision, Math, Coding, etc.) are now dynamically loaded
by `core/config/default_config.py` from `core/config/base/*_models.py`.
"""

ROUTER_CHAINS = {
    "google": ["google", "google", "mistral", "groq"],
    "mistral": ["mistral", "google"],
    "groq": ["groq", "cerebras", "google"],
    "cerebras": ["cerebras", "groq", "google"],
    "cohere": ["cohere", "google"],
    "paranoid-mode": [
        "gemini-2.0-flash",
        "gemini-2.5-flash",
        "llama-3.3-70b-versatile",
        "google"
    ]
}
