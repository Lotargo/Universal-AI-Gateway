"""
Configuration for Coding Models grouped by quality tiers.
This file is integrated into the core model configuration.
"""

CODING_TIERS = {
    # Tier 1: Software Architects.
    # Capable of complex refactoring, writing entire modules, and finding subtle bugs.
    "coding_tier_1": [
        "codestral-latest",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-pro-latest",
        "gpt-oss-120b",           # Cerebras
        "openai/gpt-oss-120b"     # Groq
    ],

    # Tier 2: Senior Developers.
    # Writes clean, idiomatic code. Good at standard algorithms and APIs.
    "coding_tier_2": [
        "gemini-2.0-flash",
        "llama-3.3-70b",
        "command-r-08-2024",
        "qwen-3-235b-a22b-instruct-2507",
        "codestral-2501",
        "devstral-medium-latest", # Mistral (Explicitly for dev)
        "qwen/qwen3-32b",         # Groq
        "zai-glm-4.6",            # Cerebras
        "moonshotai/kimi-k2-instruct"
    ],

    # Tier 3: Junior Developers.
    # Can write functional code but may miss edge cases or best practices.
    "coding_tier_3": [
        "mistral-small-latest",
        "gemma-3-27b-it",
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
        "devstral-small-latest",  # Mistral
        "openai/gpt-oss-20b",     # Groq
        "open-mistral-nemo",      # Mistral
        "gemini-2.5-flash-lite"   # Google
    ],

    # Tier 4: Beginners / Snippet Generators.
    # Good for one-liners, basic functions, or explaining code.
    "coding_tier_4": [
        "ministral-8b-latest",
        "gemma-3-12b-it",
        "gemini-2.0-flash-lite",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "open-mistral-7b"
    ],

    # Tier 5: Hello World.
    # struggle with context or syntax in complex languages.
    "coding_tier_5": [
        "mistral-tiny",
        "gemma-3-4b-it",
        "ministral-3b-latest",
        "voxtral-mini-latest"
    ]
}
