"""
Configuration for the Standard (Basic) Agent.
This agent uses a mix of lightweight and efficient models from various providers.
"""

AGENT_CONFIG = {
    "name": "mcp_agent",
    "description": "A balanced, general-purpose agent using efficient models.",
    "aliases": [],
    "instructions": """
You are a Standard AI Assistant.
Your goal is to provide helpful, accurate, and concise responses to user queries.

GUIDELINES:
1. Answer directly and clearly.
2. For simple queries, be concise.
3. For complex queries, structure your answer with headings and bullet points.
4. If you are unsure, admit it rather than guessing.
""",
    "router_config": {
        "main": [
            # Groq
            "openai/gpt-oss-120b",
            # Google
            "gemini-2.5-flash-lite",
            # Cerebras
            "gpt-oss-120b",
            # Groq
            "openai/gpt-oss-20b",
            # mistral
            "mistral-medium",
            # Groq
            "openai/gpt-oss-safeguard-20b",
            # Cerebras            
            "qwen-3-235b-a22b-instruct-2507",
            # Groq
            "llama-3.3-70b-versatile",
            # Cerebras     
            "zai-glm-4.6"
        ],
        "fallbacks": [
            # Groq
            "openai/gpt-oss-120b",
            # Google
            "gemini-2.5-flash-lite",
            # Cerebras
            "gpt-oss-120b",
            # Groq
            "openai/gpt-oss-20b",
            # mistral
            "mistral-medium",
            # Groq
            "openai/gpt-oss-safeguard-20b",
            # Cerebras            
            "qwen-3-235b-a22b-instruct-2507",
            # Groq
            "llama-3.3-70b-versatile",
            # Cerebras     
            "zai-glm-4.6"
        ]
    },
    "tools": [
        "search_tool"
    ],
    "settings": {
        "temperature": 1.0,
        "agent_settings": {
            "reasoning_mode": None, # Standard profile (Vanilla)
            "output_format": "native_reasoning"
        }
    }
}
