"""
Configuration for the OpenAI-Compatible Reasoning Agent.
This agent is specialized for deep thinking using models that support
the 'reasoning_content' field or native <think> tags (e.g., DeepSeek-R1, Groq).
It intentionally excludes Gemini Thinking models which require a different stateful protocol.
"""

from core.config.base.reasoning_models import REASONING_MODEL_CONFIGS

# Dynamically load all reasoning models defined in the configuration
REASONING_MODELS_LIST = list(REASONING_MODEL_CONFIGS.keys())

AGENT_CONFIG = {
    "name": "openai_compatible_reasoning_mode",
    "description": "A specialized agent for Deep Reasoning tasks using OpenAI-compatible Thinking Models.",
    "aliases": [], 
    "instructions": """
You are a Reasoning AI Assistant.
Your goal is to solve complex problems by thinking deeply before answering.

GUIDELINES:
1. Use your internal reasoning capabilities (Chain of Thought) to analyze the problem.
2. Break down complex tasks into logical steps.
3. Validate your assumptions and double-check your calculations.
4. Provide a clear, structured final answer after your reasoning process.
""",
    "router_config": {
        "main": REASONING_MODELS_LIST,
        "fallbacks": list(reversed(REASONING_MODELS_LIST))
    },
    "tools": [], # Native reasoning mode usually bypasses external tools in this architecture
    "settings": {
        "temperature": 0.6, # Lower temperature recommended for reasoning models
        "agent_settings": {
            "reasoning_mode": None, # Explicitly disable ReAct to use Native/Simple Chat Driver
            "output_format": "native_reasoning" # Enables <think> tag display
        }
    }
}
