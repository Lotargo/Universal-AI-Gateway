"""
Configuration for Vision Models grouped by quality tiers.
This file is integrated into the core model configuration.

Verification methods:
- Google: Native File API (Upload to Key Storage) -> Model API
- Others (Mistral, Groq, Cohere): Public URL -> Model API (via Cloudinary logic in prod)
"""

VISION_TIERS = {
    # Tier 1: Excellent, detailed, and stylistically accurate description.
    # Capable of deep reasoning ("Thinking") about the image content.
    "vision_tier_1": [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-pro-latest",  # Promoted from Tier 2
        "gemini-flash-latest",
        "gemini-2.5-flash-preview-09-2025"
    ],

    # Tier 2: Detailed and accurate description.
    # Good for general purpose vision tasks.
    "vision_tier_2": [
        "gemini-2.0-flash",
        "gemini-flash-lite-latest",
        "gemini-2.5-flash-lite-preview-09-2025",
        "gemini-robotics-er-1.5-preview",
        "gemini-2.0-flash-lite"
    ],

    # Tier 3: Competent but basic description.
    # Misses some fine details or precise counts.
    "vision_tier_3": [
        "gemma-3-12b-it",
        "gemma-3-27b-it",
        "meta-llama/llama-4-maverick-17b-128e-instruct"  # Groq (Experimental)
    ],

    # Tier 4: Too brief, generalized, or prone to minor errors.
    "vision_tier_4": [
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-lite-001",
        "gemini-2.0-flash-lite-preview-02-05",
        "gemini-2.5-flash-lite",
        "command-a-vision-07-2025",  # Cohere
        "mistral-large-pixtral-2411",# Mistral
        "pixtral-large-latest",      # Mistral
        "pixtral-12b-2409",          # Mistral
        "pixtral-12b",
        "mistral-small-latest",      # Mistral
        "meta-llama/llama-4-scout-17b-16e-instruct" # Groq (Experimental)
    ],

    # Tier 5: Description with inaccuracies, hallucinations, or very poor detail.
    "vision_tier_5": [
        "gemma-3-4b-it",
        "c4ai-aya-vision-32b",  # Cohere
        "c4ai-aya-vision-8b",
        "magistral-medium-latest", # Mistral
        "magistral-small-latest"   # Mistral
    ]
}
