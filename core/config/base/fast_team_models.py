"""
Configuration for fastests Models.
This file is integrated into the core model configuration.
"""

FAST_MODELS = {
    "fast_gpt_120b": [
            # Sambanova
            "sambanova/gpt-oss-120b",
            # Groq
            "openai/gpt-oss-120b",
            # Cerebras
            "gpt-oss-120b"
    ]
}
