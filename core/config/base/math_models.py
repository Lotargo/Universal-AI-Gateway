"""
Configuration for Math Models grouped by quality tiers.
This file is integrated into the core model configuration.
"""

MATH_TIERS = {
    # Tier 1: Mathematical Masters.
    # Capable of complex multi-step reasoning, calculus, and logic puzzles.
    # Seldom fail "trick" questions.
    "math_tier_1": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "llama-3.3-70b",
        "command-r-08-2024",
        "gemini-2.5-flash-preview-09-2025",
        "gpt-oss-120b",           # Cerebras (Large open model)
        "openai/gpt-oss-120b"     # Groq (Large open model)
    ],

    # Tier 2: Strong Solvers.
    # Good for algebra, geometry, and standard university-level math.
    # May stumble on subtle logic traps.
    "math_tier_2": [
        "gemini-2.0-flash",
        "codestral-latest",
        "mistral-medium",
        "mistral-large-2411",
        "gemini-2.0-flash-001",
        "qwen/qwen3-32b",         # Groq (Strong Qwen variant)
        "zai-glm-4.6",            # Cerebras (GLM is math-strong)
        "moonshotai/kimi-k2-instruct", # Groq (Good reasoning)
        "command-a-03-2025"       # Cohere
    ],

    # Tier 3: Competent.
    # Solid for high-school math and basic stats.
    "math_tier_3": [
        "mistral-small-latest",
        "gemma-3-27b-it",
        "qwen-3-235b-a22b-instruct-2507",
        "c4ai-aya-expanse-32b",
        "openai/gpt-oss-20b",     # Groq
        "open-mistral-nemo",      # Mistral
        "gemini-2.5-flash-lite",  # Google (New lite)
        "devstral-medium-latest", # Mistral
        "groq/compound"           # Groq
    ],

    # Tier 4: Basic.
    # Can solve arithmetic and simple algebra. Fails logic traps frequently.
    "math_tier_4": [
        "llama-3.1-8b-instant",
        "ministral-8b-latest",
        "gemini-2.0-flash-lite",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "open-mistral-7b",
        "allam-2-7b",             # Groq
        "groq/compound-mini",     # Groq
        "command-r7b-12-2024"     # Cohere
    ],

    # Tier 5: Weak / Unreliable.
    # Prone to hallucinations in reasoning chains.
    "math_tier_5": [
        "mistral-tiny",
        "gemma-3-4b-it",
        "gemma-3-12b-it",
        "ministral-3b-latest",
        "voxtral-mini-latest",
        "voxtral-small-latest"
    ]
}
