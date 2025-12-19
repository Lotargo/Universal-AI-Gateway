"""Registry of versioned model aliases used for rotation."""

MODEL_ALIASES = {
    "google": {
        "gemini-2.0-flash": [
            "gemini-2.0-flash",
            "gemini-2.0-flash-001"
        ],
        "gemini-2.0-flash-lite": [
            "gemini-2.0-flash-lite",
            "gemini-2.0-flash-lite-001",
            "gemini-2.0-flash-lite-preview",
            "gemini-2.0-flash-lite-preview-02-05"
        ],
        "gemini-2.5-flash": [
            "gemini-2.5-flash",
            "gemini-2.5-flash-preview-09-2025",
            "gemini-flash-latest"
        ],
        "gemini-2.5-flash-lite": [
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash-lite-preview-09-2025",
            "gemini-flash-lite-latest"
        ],
        "gemini-2.5-pro": [
            "gemini-2.5-pro",
            "gemini-pro-latest"
        ],
        "gemini-robotics-er-1.5-preview": [
            "gemini-robotics-er-1.5-preview"
        ],
        "gemma": [
            "gemma-3-12b-it",
            "gemma-3-27b-it"
        ],
        "gemma-tiny": [
            "gemma-3-1b-it",
            "gemma-3-4b-it",
            "gemma-3n-e2b-it",
            "gemma-3n-e4b-it"
        ]
    },
    "mistral": {
        "codestral": [
            "codestral-2411-rc5",
            "codestral-2412",
            "codestral-2501",
            "codestral-2508",
            "codestral-latest"
        ],
        "devstral-medium": [
            "devstral-medium-2507",
            "devstral-medium-latest"
        ],
        "devstral-small": [
            "devstral-small-2505",
            "devstral-small-2507",
            "devstral-small-latest"
        ],
        "magistral-medium": [
            "magistral-medium-2506",
            "magistral-medium-2507",
            "magistral-medium-2509",
            "magistral-medium-latest"
        ],
        "magistral-small": [
            "magistral-small-2506",
            "magistral-small-2507",
            "magistral-small-2509",
            "magistral-small-latest"
        ],
        "ministral-3b": [
            "ministral-3b-2410",
            "ministral-3b-latest"
        ],
        "ministral-8b": [
            "ministral-8b-2410",
            "ministral-8b-latest"
        ],
        "mistral-large": [
            "mistral-large-2411"
        ],
        "mistral-large-pixtral": [
            "mistral-large-pixtral-2411"
        ],
        "mistral-medium": [
            "mistral-medium",
            "mistral-medium-2508"
        ],
        "mistral-small": [
            "mistral-small-2409",
            "mistral-small-2501",
            "mistral-small-2503",
            "mistral-small-2506",
            "mistral-small-latest"
        ],
        "mistral-tiny": [
            "mistral-tiny",
            "mistral-tiny-2312",
            "mistral-tiny-2407",
            "mistral-tiny-latest"
        ],
        "open-mistral-7b": [
            "open-mistral-7b"
        ],
        "open-mistral-nemo": [
            "open-mistral-nemo",
            "open-mistral-nemo-2407"
        ],
        "pixtral-12b": [
            "pixtral-12b",
            "pixtral-12b-2409",
            "pixtral-12b-latest"
        ],
        "pixtral-large": [
            "pixtral-large-2411",
            "pixtral-large-latest"
        ],
        "voxtral-mini": [
            "voxtral-mini-2507",
            "voxtral-mini-latest"
        ],
        "voxtral-small": [
            "voxtral-small-2507",
            "voxtral-small-latest"
        ]
    },
    "cerebras": {
        "gpt-oss-120b": [
            "gpt-oss-120b"
        ],
        "llama-3.3-70b": [
            "llama-3.3-70b"
        ],
        "llama3.1-8b": [
            "llama3.1-8b"
        ],
        "qwen-3-235b-a22b-instruct-2507": [
            "qwen-3-235b-a22b-instruct-2507"
        ],
        "zai-glm-4.6": [
            "zai-glm-4.6"
        ]
    },
    "groq": {
        "allam-2-7b": [
            "allam-2-7b"
        ],
        "groq/compound": [
            "groq/compound"
        ],
        "groq/compound-mini": [
            "groq/compound-mini"
        ],
        "llama-3.1-8b-instant": [
            "llama-3.1-8b-instant"
        ],
        "llama-3.3-70b-versatile": [
            "llama-3.3-70b-versatile"
        ],
        "meta-llama/llama-4-maverick-17b-128e-instruct": [
            "meta-llama/llama-4-maverick-17b-128e-instruct"
        ],
        "meta-llama/llama-4-scout-17b-16e-instruct": [
            "meta-llama/llama-4-scout-17b-16e-instruct"
        ],
        "meta-llama/llama-guard-4-12b": [
            "meta-llama/llama-guard-4-12b"
        ],
        "meta-llama/llama-prompt-guard-2-22m": [
            "meta-llama/llama-prompt-guard-2-22m"
        ],
        "meta-llama/llama-prompt-guard-2-86m": [
            "meta-llama/llama-prompt-guard-2-86m"
        ],
        "moonshotai/kimi-k2-instruct": [
            "moonshotai/kimi-k2-instruct"
        ],
        "moonshotai/kimi-k2-instruct-0905": [
            "moonshotai/kimi-k2-instruct-0905"
        ],
        "openai/gpt-oss-120b": [
            "openai/gpt-oss-120b"
        ],
        "openai/gpt-oss-20b": [
            "openai/gpt-oss-20b"
        ],
        "openai/gpt-oss-safeguard-20b": [
            "openai/gpt-oss-safeguard-20b"
        ],
        "qwen/qwen3-32b": [
            "qwen/qwen3-32b"
        ]
    },
    "cohere": {
        "c4ai-aya-expanse-32b": [
            "c4ai-aya-expanse-32b"
        ],
        "c4ai-aya-vision-32b": [
            "c4ai-aya-vision-32b"
        ],
        "c4ai-aya-vision-8b": [
            "c4ai-aya-vision-8b"
        ],
        "command-a-03-2025": [
            "command-a-03-2025"
        ],
        "command-a-translate-08-2025": [
            "command-a-translate-08-2025"
        ],
        "command-a-vision-07-2025": [
            "command-a-vision-07-2025"
        ],
        "command-r-08-2024": [
            "command-r-08-2024"
        ],
        "command-r7b-12-2024": [
            "command-r7b-12-2024"
        ]
    },
    "sambanova": {
        "sambanova/gpt-oss-120b": [
            "gpt-oss-120b"
        ],        
        "ALLaM-7B-Instruct-preview": [
            "ALLaM-7B-Instruct-preview"
        ],
        "DeepSeek-R1-0528": [
            "DeepSeek-R1-0528"
        ],
        "DeepSeek-R1-Distill-Llama-70B": [
            "DeepSeek-R1-Distill-Llama-70B"
        ],
        "DeepSeek-V3-0324": [
            "DeepSeek-V3-0324"
        ],
        "DeepSeek-V3.1": [
            "DeepSeek-V3.1"
        ],
        "DeepSeek-V3.1-Terminus": [
            "DeepSeek-V3.1-Terminus"
        ],
        "E5-Mistral-7B-Instruct": [
            "E5-Mistral-7B-Instruct"
        ],
        "Llama-3.3-Swallow-70B-Instruct-v0.4": [
            "Llama-3.3-Swallow-70B-Instruct-v0.4"
        ],
        "Llama-4-Maverick-17B-128E-Instruct": [
            "Llama-4-Maverick-17B-128E-Instruct"
        ],
        "Meta-Llama-3.1-8B-Instruct": [
            "Meta-Llama-3.1-8B-Instruct"
        ],
        "Meta-Llama-3.3-70B-Instruct": [
            "Meta-Llama-3.3-70B-Instruct"
        ],
        "Qwen3-235B": [
            "Qwen3-235B"
        ],
        "Qwen3-32B": [
            "Qwen3-32B"
        ],
        "Whisper-Large-v3": [
            "Whisper-Large-v3"
        ]
    }
}
