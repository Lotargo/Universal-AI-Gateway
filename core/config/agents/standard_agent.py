"""
Configuration for the Standard (Basic) Agent.
This agent uses a mix of lightweight and efficient models from various providers.
"""

AGENT_CONFIG = {
    "name": "standard_agent",
    "description": "A balanced, general-purpose agent using efficient models.",
    "instructions": """
You are a Standard AI Assistant.
Your goal is to provide helpful, accurate, and concise responses to user queries.

{tools_list_text}

{tool_instructions}

GUIDELINES:
1. Answer directly and clearly.
2. For simple queries, be concise.
3. For complex queries, structure your answer with headings and bullet points.
4. If you are unsure, admit it rather than guessing.
""",
    "router_config": {
        "main": ["fast_gpt_120b"],
        "fallbacks": ["fast_gpt_120b"]
    },
    "tools": [
        "search_tool"
    ],
    "settings": {
        "temperature": 1.0,
        "agent_settings": {
            "reasoning_mode": "native_tool_calling",
            "output_format": "native_reasoning"
        }
    }
}
