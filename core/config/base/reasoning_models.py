
"""
Configuration for provider-specific reasoning capabilities.
Maps model IDs to their required API parameters for enabling/tuning reasoning.
"""

REASONING_MODEL_CONFIGS = {
    # --- CEREBRAS ---
    "gpt-oss-120b": {
        "provider": "cerebras",
        "params": {
            "reasoning_effort": "high"  # Options: low, medium, high
        },
        "output_handling": "delta_reasoning_field" # Looks for delta.reasoning
    },
    "zai-glm-4.6": {
        "provider": "cerebras",
        "params": {
            # "disable_reasoning": False # Deprecated or not supported, removed to avoid 422
        },
        "output_handling": "delta_reasoning_field"
    },

    # --- GROQ ---
    "openai/gpt-oss-120b": {
        "provider": "groq",
        "params": {
            "reasoning_effort": "high"
            # "reasoning_format": "raw" # Not supported for this model, returns 'reasoning' field
        },
        "output_handling": "delta_reasoning_field"
    },
    "openai/gpt-oss-20b": {
        "provider": "groq",
        "params": {
            "reasoning_effort": "high"
        },
        "output_handling": "delta_reasoning_field"
    },
    "qwen/qwen3-32b": {
        "provider": "groq",
        "params": {
            "reasoning_effort": "default", # none, default
            "reasoning_format": "raw"
        },
        "output_handling": "content_think_tags"
    },

    # --- MISTRAL ---
    "magistral-medium-latest": {
        "provider": "mistral",
        "params": {
            "prompt_mode": "reasoning" # Explicitly request reasoning system prompt
        },
        "output_handling": "structured_content" # Handled by existing Mistral parser
    },
    "magistral-small-latest": {
        "provider": "mistral",
        "params": {
            "prompt_mode": "reasoning"
        },
        "output_handling": "structured_content"
    },

    # --- SAMBANOVA ---
    "DeepSeek-R1-0528": {
        "provider": "sambanova",
        "params": {},
        "output_handling": "delta_reasoning_field" # Sambanova returns reasoning in delta
    },
    "DeepSeek-R1-Distill-Llama-70B": {
        "provider": "sambanova",
        "params": {},
        "output_handling": "delta_reasoning_field"
    }
}
