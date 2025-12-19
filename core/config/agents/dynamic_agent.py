"""Configuration for the Dynamic Agent.

This agent uses a hybrid reasoning engine.
"""

AGENT_CONFIG = {
    "name": "dynamic-agent",
    "aliases": [],
    "description": "Smart agent with dynamic hybrid reasoning capabilities.",

    "settings": {
        "temperature": 0.8,
        "top_p": 0.9,
        "agent_settings": {
            "reasoning_mode": "dynamic_hybrid",
            "output_format": "native_reasoning"
        }
    },

    "router_config": {
        "main": [
            "gemini-2.5-flash-lite"
        ],
        "fallbacks": [
            "mistral-small"
        ]
    }
}
