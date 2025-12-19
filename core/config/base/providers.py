"""Active model definitions for general purpose providers.

Defines which models are active for each provider.
Dynamically loads all aliases defined in core.config.base.models to ensure
full compatibility with any configured alias.
"""

from core.config.base.models import MODEL_ALIASES

# Dynamically populate active models from the registry of aliases.
# This ensures that any alias defined in MODEL_ALIASES is automatically
# considered an "active" model candidate for the provider.
PROVIDER_MODELS = {
    provider: list(aliases.keys())
    for provider, aliases in MODEL_ALIASES.items()
}
