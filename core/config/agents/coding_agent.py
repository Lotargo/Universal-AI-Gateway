"""
Configuration for the specialized Coding Agent.
"""

AGENT_CONFIG = {
    "name": "coding_agent",
    "description": "Specialized agent for software development, debugging, and code generation.",
    "aliases": [], 
    "instructions": """
You are a Senior Software Engineer Agent.
Your goal is to write high-quality, maintainable, and efficient code.

GUIDELINES:
1. Always write clean, idiomatic code following standard style guides (e.g., PEP 8 for Python).
2. When debugging, explain the root cause of the error before providing the fix.
3. If writing a full module, structure it properly with imports and comments.
4. Security First: Do not write code that is vulnerable to SQL injection, XSS, or other common flaws.
5. Use the Python Code Interpreter to verify snippets if they are self-contained.
""",
    "router_config": {
        "main": [
            "coding_tier_3",
            "coding_tier_2"
        ],
        "fallbacks": [
            "coding_tier_3"
        ]
    },
    "tools": [
        "python_repl",
        "search_tool",
        "file_tools" # Useful for reading/writing code files if context allows
    ],
    "settings": {
        "temperature": 0.1, # Very low temperature for code determinism
        "agent_settings": {
            "reasoning_mode": "native_tool_calling", 
            "output_format": "native_reasoning"
        }
    }
}
