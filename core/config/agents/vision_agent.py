"""
Configuration for the specialized Vision Agent.
This agent is designed for high-fidelity image analysis and reasoning.
"""

AGENT_CONFIG = {
    "name": "vision-agent",
    "description": "A specialized agent for analyzing images and visual data.",
    "aliases": [], 
    # Optional system instruction (if supported by loader, otherwise informational)
    "system_instruction": (
        "You are an advanced Vision Agent. Your primary capability is to interpret visual information.\n"
        "When analyzing images:\n"
        "1. Be extremely detailed and precise.\n"
        "2. List objects, colors, and text verbatim.\n"
        "3. If reasoning is required, explain your visual evidence step-by-step.\n"
        "4. Do not hallucinate details that are not present."
    ),

    # Runtime generation settings
    "settings": {
        "temperature": 0.2, # Lower temperature for precise vision tasks
        "top_p": 0.95,
        "agent_settings": {
            "reasoning_mode": "native_tool_calling",  
            "output_format": "native_reasoning"
        }
    },

    # Using the Tier 2 Vision models by default (defined in core/config/base/vision_models.py)
    "router_config": {
        "main": ["vision_tier_2"],
        "fallbacks": ["vision_tier_3"]
    }
}
