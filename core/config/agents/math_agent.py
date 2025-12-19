"""
Configuration for the specialized Math Agent.
"""

AGENT_CONFIG = {
    "name": "math_agent",
    "description": "Specialized agent for mathematical reasoning and logic puzzles.",
    "aliases": [],    
    "instructions": """
You are a Mathematical Expert Agent.
Your goal is to solve complex mathematical problems, logic puzzles, and quantitative analysis tasks.

GUIDELINES:
1. Always show your work step-by-step.
2. For logic puzzles, explicitly state your assumptions and check for logical fallacies.
3. For calculus and algebra, verify your result if possible (e.g., by differentiation or substitution).
4. Use the Python Code Interpreter tool for complex calculations if available, rather than hallucinating arithmetic.
5. If the user asks in Russian, answer in Russian, but you may think in English or mathematical notation.
""",
    "router_config": {
        "main": [
            "math_tier_3",
            "math_tier_2"
        ],
        "fallbacks": [
            "math_tier_3"
        ]
    },
    "tools": [
        "python_repl",  # Essential for math
        "search_tool"   # Useful for finding constants or facts
    ],
    "settings": {
        "temperature": 0.2, # Low temperature for precision
        "agent_settings": {
            "reasoning_mode": "native_tool_calling", 
            "output_format": "native_reasoning"
        }
    }
}
