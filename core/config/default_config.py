import os
import pkgutil
import importlib
import logging
import copy

# Import modular configurations
from core.config.base.providers import PROVIDER_MODELS
from core.config.base.models import MODEL_ALIASES
from core.config.base.routing import ROUTER_CHAINS
from core.config.base.mutation_exclusions import MUTATION_EXCLUSION_LIST
from core.config.base.settings import (
    MCP_SERVERS, CACHE_SETTINGS, KEY_MANAGEMENT_SETTINGS,
    AUTH_SETTINGS, AGENT_SETTINGS, NATIVE_TOOL_TOGGLES, ENRICHMENT_SETTINGS,
    ENABLE_SMART_SEARCH
)

logger = logging.getLogger("UniversalAIGateway")

"""Default configuration for the application.

This module orchestrates the model configuration, routing logic, and fallback strategies.
It uses modular definitions from `core.config.base` and `core.config.agents`
to programmatically generate model profiles and aliases.
"""

# =============================================================================
# --- CORE LOGIC & GENERATION -------------------------------------------------
# =============================================================================

MODEL_LIST = []
MODEL_GROUP_ALIAS = {}
AGENT_ROUTING_METADATA = {} # New: Stores metadata for runtime load balancing
PROVIDERS = list(PROVIDER_MODELS.keys())
ACTIVE_PROFILE_MAP = {} # Maps alias/model_id -> {provider: ..., models: ...}

REASONING_MODES = {
    "standard-chat": None,
    "linear-react": "linear_react",
    "analytical-react": "analytical_react",
    "sonata-react": "sonata_react",
}

DEEP_THOUGHT_VARIANTS = {
    "deep-thought": "linear_react",
}

def resolve_alias_to_model_list(provider, alias):
    """Resolves a single alias name to its underlying list of model IDs."""
    if alias in MODEL_ALIASES.get(provider, {}):
        return MODEL_ALIASES[provider][alias]
    return [alias]

# --- 0. Dynamic Loading of Model Tiers (Scanning core/config/base/) ---
# Automatically scan for files ending in `_models.py` and register any `*_TIERS` dictionaries
# into ROUTER_CHAINS. This removes the need for manual imports of new tiers.

import core.config.base as base_pkg

for _, name, _ in pkgutil.iter_modules(base_pkg.__path__):
    if name.endswith("_models"):
        try:
            module = importlib.import_module(f"core.config.base.{name}")
            # Scan for any attribute ending in _TIERS or _MODELS that is a dict
            # This allows user-defined model lists (e.g. FAST_MODELS) to be auto-loaded.
            for attr_name in dir(module):
                if (attr_name.endswith("_TIERS") or attr_name.endswith("_MODELS")) and attr_name != "PROVIDER_MODELS":
                    attr_value = getattr(module, attr_name)
                    if isinstance(attr_value, dict):
                        # Merge into ROUTER_CHAINS
                        ROUTER_CHAINS.update(attr_value)
                        logger.info(f"Dynamically loaded tiers/models from {name}.{attr_name}")
        except Exception as e:
            logger.error(f"Failed to dynamically load tiers from {name}: {e}")

# --- 1. Pre-process Standard Providers and Models (Build Lookup Map) ---
# We need this BEFORE processing agents so we can lookup providers for aliases.

for provider, model_ref in PROVIDER_MODELS.items():
    provider_combined_models = []

    # Process specific models/aliases defined for the provider
    if isinstance(model_ref, list):
        for specific_model_alias in model_ref:
            resolved_models = resolve_alias_to_model_list(provider, specific_model_alias)
            provider_combined_models.extend(resolved_models)

            # Map the alias to the provider
            ACTIVE_PROFILE_MAP[specific_model_alias] = {
                "provider": provider,
                "models": specific_model_alias # Use the alias string
            }

            # Map each specific model ID to the provider as well.
            # This allows direct targeting of specific model versions (e.g. in Vision Tiers)
            # while ensuring they are correctly associated with their provider for upload/cache logic.
            for model_id in resolved_models:
                if model_id not in ACTIVE_PROFILE_MAP:
                    ACTIVE_PROFILE_MAP[model_id] = {
                        "provider": provider,
                        "models": model_id  # Map to itself for direct access
                    }
    else:
        # Single string model
        ACTIVE_PROFILE_MAP[model_ref] = {
            "provider": provider,
            "models": model_ref
        }
        provider_combined_models.extend(resolve_alias_to_model_list(provider, model_ref))

    # Register combined alias for the provider
    combined_alias_name = f"{provider}-combined"
    if provider not in MODEL_ALIASES:
        MODEL_ALIASES[provider] = {}
    MODEL_ALIASES[provider][combined_alias_name] = provider_combined_models

    ACTIVE_PROFILE_MAP[provider] = {
        "provider": provider,
        "models": combined_alias_name # Use the alias string
    }


def create_agent_stack(agent_config):
    """Generates profiles and router chains from a unified agent config object."""
    agent_name = agent_config["name"]
    settings = agent_config.get("settings", {})
    aliases = agent_config.get("aliases", [])

    # Handle new router_config structure vs old router_chain
    router_config = agent_config.get("router_config", {})
    if not router_config and "router_chain" in agent_config:
        # Legacy/Simple mode support
        main_chain = agent_config["router_chain"]
        fallback_chain = []
    else:
        main_chain = router_config.get("main", [])
        fallback_chain = router_config.get("fallbacks", [])

    full_chain = main_chain + fallback_chain
    router_list = []

    # Track how many profiles are generated from the main chain items
    # to accurately set the load balancing pool size.
    main_profile_count = 0

    for i, alias_or_provider in enumerate(full_chain):
        # Determine provider and model alias
        provider = None
        model_alias = alias_or_provider

        # 1. Check if it is a specific alias we know about
        if alias_or_provider in ACTIVE_PROFILE_MAP:
            data = ACTIVE_PROFILE_MAP[alias_or_provider]
            provider = data["provider"]
            model_alias = data["models"]
        # 2. Check if it is a provider name (fallback to combined)
        elif alias_or_provider in PROVIDERS:
            provider = alias_or_provider
            model_alias = f"{provider}-combined"
        # 3. Check if it is a Router Chain (e.g. vision_tier_1)
        elif alias_or_provider in ROUTER_CHAINS:
            # Handle Router Chains (e.g. vision_tier_1) by iterating through items
            chain_items = ROUTER_CHAINS[alias_or_provider]
            for sub_item in chain_items:
                # Resolve sub_item
                sub_provider = None
                sub_alias = sub_item

                if sub_item in ACTIVE_PROFILE_MAP:
                    sub_data = ACTIVE_PROFILE_MAP[sub_item]
                    sub_provider = sub_data["provider"]
                    sub_alias = sub_data["models"]
                elif sub_item in PROVIDERS:
                    sub_provider = sub_item
                    sub_alias = f"{sub_item}-combined"
                else:
                    logger.warning(f"Agent '{agent_name}': Could not resolve sub-item '{sub_item}' in chain '{alias_or_provider}'. Skipping.")
                    continue

                # --- EXPANSION LOGIC FOR SUB-ITEM ---
                # Check if sub_alias is itself a group alias in MODEL_ALIASES
                # If so, expand it to individual models to ensure failover works correctly.
                models_to_add = [sub_alias]
                if sub_provider in MODEL_ALIASES and sub_alias in MODEL_ALIASES[sub_provider]:
                     models_to_add = MODEL_ALIASES[sub_provider][sub_alias]
                     # If the list is empty, revert to alias (though unlikely)
                     if not models_to_add:
                         models_to_add = [sub_alias]

                for j, concrete_model in enumerate(models_to_add):
                    # Create profile for this concrete model
                    # Use index 'j' to distinguish variations
                    sub_profile_name = f"{agent_name}-step-{i}-{sub_item}-{j}-profile"

                    model_list_entry = {
                        "model_name": sub_profile_name,
                        "provider": sub_provider,
                        "tier": "special",
                        "model_params": {
                            "temperature": settings.get("temperature", 0.7),
                            "top_p": settings.get("top_p", 0.95),
                            "max_tokens": settings.get("max_tokens", None),
                            "model": concrete_model, # Point to concrete ID
                            "agent_settings": settings.get("agent_settings", {}),
                        }
                    }
                    if sub_provider == "groq":
                        model_list_entry["model_params"]["api_base"] = "https://api.groq.com/openai/v1"
                    if sub_provider == "cerebras":
                        model_list_entry["model_params"]["api_base"] = "https://api.cerebras.ai/v1"

                    MODEL_LIST.append(model_list_entry)
                    router_list.append(sub_profile_name)

                    # Increment count if this item belongs to the main chain
                    if i < len(main_chain):
                        main_profile_count += 1

            continue

        else:
            logger.warning(f"Agent '{agent_name}': Could not resolve provider for chain item '{alias_or_provider}'. Skipping.")
            continue

        # --- EXPANSION LOGIC FOR MAIN ITEM ---
        # Same logic for top-level chain items: expand if alias
        models_to_add = [model_alias]
        if provider in MODEL_ALIASES and model_alias in MODEL_ALIASES[provider]:
             models_to_add = MODEL_ALIASES[provider][model_alias]
             if not models_to_add:
                 models_to_add = [model_alias]

        for j, concrete_model in enumerate(models_to_add):
            profile_name = f"{agent_name}-step-{i}-{j}-profile"

            model_list_entry = {
                "model_name": profile_name,
                "provider": provider,
                "tier": "special",
                "model_params": {
                    "temperature": settings.get("temperature", 0.7),
                    "top_p": settings.get("top_p", 0.95),
                    "max_tokens": settings.get("max_tokens", None),
                    "model": concrete_model, # Point to concrete ID
                    "agent_settings": settings.get("agent_settings", {}),
                }
            }

            if provider == "groq":
                model_list_entry["model_params"]["api_base"] = "https://api.groq.com/openai/v1"
            if provider == "cerebras":
                model_list_entry["model_params"]["api_base"] = "https://api.cerebras.ai/v1"

            MODEL_LIST.append(model_list_entry)
            router_list.append(profile_name)

            if i < len(main_chain):
                main_profile_count += 1

    if router_list:
        MODEL_GROUP_ALIAS[agent_name] = router_list
        for alias in aliases:
            MODEL_GROUP_ALIAS[alias] = router_list

        # Store metadata for runtime load balancing
        # We need to know how many items belong to "main" pool to rotate them
        # Verify that we successfully created profiles for all main items
        # If some were skipped due to errors, main_profile_count might be off.
        # But for now assuming configuration validity.
        if main_profile_count > 1:
            AGENT_ROUTING_METADATA[agent_name] = {"main_length": main_profile_count}
            for alias in aliases:
                AGENT_ROUTING_METADATA[alias] = {"main_length": main_profile_count}

    else:
        logger.error(f"Agent '{agent_name}' has no valid models in router chain!")


# --- 2. Load and Process Agent Configurations ---

import core.config.agents as agents_pkg

# Dynamic Pattern Loading
# Scans `react_patterns/` for files ending in `_react.py` (e.g., `linear_react.py`)
# and registers them as mutations (e.g., `linear` -> `linear_react`).
REACT_MUTATIONS = {}
react_patterns_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "react_patterns")

if os.path.exists(react_patterns_path):
    for filename in os.listdir(react_patterns_path):
        if filename.endswith("_react.py"):
            mutation_key = filename.replace("_react.py", "")
            mutation_value = filename.replace(".py", "")
            REACT_MUTATIONS[mutation_key] = mutation_value
            logger.info(f"Discovered ReAct pattern mutation: {mutation_key} -> {mutation_value}")

# Fallback/Ensure defaults if directory scan fails or is empty (though unlikely)
if "linear" not in REACT_MUTATIONS:
    REACT_MUTATIONS["linear"] = "linear_react"
if "analytical" not in REACT_MUTATIONS:
    REACT_MUTATIONS["analytical"] = "analytical_react"
if "sonata" not in REACT_MUTATIONS:
    REACT_MUTATIONS["sonata"] = "sonata_react"

# Dynamically load all modules in core.config.agents
for _, name, _ in pkgutil.iter_modules(agents_pkg.__path__):
    # FILTER: Only load modules that have "agent" in their name.
    # This prevents loading helper files or garbage modules.
    if "agent" in name:
        try:
            module = importlib.import_module(f"core.config.agents.{name}")
            if hasattr(module, "AGENT_CONFIG"):
                base_config = module.AGENT_CONFIG

                # 1. Standard (Vanilla) Profile
                create_agent_stack(base_config)

                # 2. Generate Mutations (except for blacklisted agents)
                if base_config["name"] not in MUTATION_EXCLUSION_LIST:
                    for suffix, reasoning_mode in REACT_MUTATIONS.items():
                        # Deep copy to prevent mutation of the original or other variants
                        mutation_config = copy.deepcopy(base_config)

                        # Apply mutation
                        mutation_config["name"] = f"{base_config['name']}_{suffix}"
                        mutation_config["aliases"] = [] # Clear aliases for mutations to avoid collision

                        # Ensure 'settings' and 'agent_settings' exist
                        if "settings" not in mutation_config:
                            mutation_config["settings"] = {}
                        if "agent_settings" not in mutation_config["settings"]:
                            mutation_config["settings"]["agent_settings"] = {}

                        mutation_config["settings"]["agent_settings"]["reasoning_mode"] = reasoning_mode

                        create_agent_stack(mutation_config)

                logger.info(f"Loaded agent config: {name}")
        except Exception as e:
            logger.error(f"Failed to load agent config '{name}': {e}")


# --- 3. Generate Standard and Reasoning Profiles (Global) ---
# NOTE: We generate the profiles (MODEL_LIST) so they can be used as internal building blocks,
# but we DO NOT expose them in MODEL_GROUP_ALIAS anymore unless enabled.

ENABLE_STANDARD_MODEL_ALIASES = False

for profile_key, data in ACTIVE_PROFILE_MAP.items():
    provider = data["provider"]
    model_alias_or_id = data["models"]

    for alias_suffix, mode_name in REASONING_MODES.items():
        profile_name = f"{profile_key}-{alias_suffix}-profile"
        model_list_entry = {
            "model_name": profile_name,
            "provider": provider,
            "tier": "pro",
            "model_params": {
                "temperature": 0.7,
                "top_p": 0.95,
                "max_tokens": None,
                "model": model_alias_or_id,
                "agent_settings": {"reasoning_mode": mode_name},
            },
        }
        if provider == "groq":
            model_list_entry["model_params"]["api_base"] = "https://api.groq.com/openai/v1"
        if provider == "cerebras":
            model_list_entry["model_params"]["api_base"] = "https://api.cerebras.ai/v1"

        MODEL_LIST.append(model_list_entry)

        if ENABLE_STANDARD_MODEL_ALIASES and alias_suffix == "standard-chat":
            MODEL_GROUP_ALIAS[profile_key] = [profile_name]

    for suffix, mode in DEEP_THOUGHT_VARIANTS.items():
        profile_name = f"{profile_key}-{suffix}-profile"
        model_list_entry = {
            "model_name": profile_name,
            "provider": provider,
            "tier": "pro",
            "model_params": {
                "temperature": 0.7,
                "top_p": 0.95,
                "max_tokens": None,
                "model": model_alias_or_id,
                "agent_settings": {
                    "reasoning_mode": mode,
                    "output_format": "native_reasoning"
                },
            },
        }
        if provider == "groq":
            model_list_entry["model_params"]["api_base"] = "https://api.groq.com/openai/v1"
        if provider == "cerebras":
            model_list_entry["model_params"]["api_base"] = "https://api.cerebras.ai/v1"
        MODEL_LIST.append(model_list_entry)

# --- 4. Generate Router Chains ---
# NOTE: Tiers and Chains are no longer exposed directly unless enabled.
ENABLE_FULL_CHAIN_ALIASES = False

for chain_name, chain_components in ROUTER_CHAINS.items():
    # Loop kept to potentially register metadata if needed, but alias exposure is disabled.
    for alias_suffix in REASONING_MODES.keys():
        full_alias_name = f"{chain_name}-{alias_suffix}"
        profile_chain = []

        for component in chain_components:
            if component in ACTIVE_PROFILE_MAP:
                profile_name = f"{component}-{alias_suffix}-profile"
                profile_chain.append(profile_name)
            elif component in PROVIDERS:
                 pass

        if profile_chain:
            if ENABLE_FULL_CHAIN_ALIASES:
                MODEL_GROUP_ALIAS[full_alias_name] = profile_chain

            # If this is a Tier (acts as a load-balanced pool), register metadata.
            # We assume any chain starting with a known tier prefix or just having >1 items is a pool.
            # Since VISION_TIERS is now dynamic, we can just check if it's in the ROUTER_CHAINS and length > 1
            if len(profile_chain) > 1:
                AGENT_ROUTING_METADATA[full_alias_name] = {"main_length": len(profile_chain)}

    for suffix in DEEP_THOUGHT_VARIANTS.keys():
        full_alias_name = f"{chain_name}-{suffix}"
        profile_chain = []

        for component in chain_components:
            if component in ACTIVE_PROFILE_MAP:
                profile_name = f"{component}-{suffix}-profile"
                profile_chain.append(profile_name)

        if profile_chain and ENABLE_FULL_CHAIN_ALIASES:
            MODEL_GROUP_ALIAS[full_alias_name] = profile_chain

# --- 5. Generate Short Aliases for Chains ---
ENABLE_SHORT_CHAIN_ALIASES = False

if ENABLE_SHORT_CHAIN_ALIASES:
    for chain_name in ROUTER_CHAINS.keys():
        std_alias = f"{chain_name}-standard-chat"
        if std_alias in MODEL_GROUP_ALIAS:
            MODEL_GROUP_ALIAS[chain_name] = MODEL_GROUP_ALIAS[std_alias]

            # Copy metadata if exists for the standard alias (e.g. for Vision Tiers)
            if std_alias in AGENT_ROUTING_METADATA:
                AGENT_ROUTING_METADATA[chain_name] = AGENT_ROUTING_METADATA[std_alias]

# --- 6. Expose Raw Model IDs as Aliases ---
ENABLE_RAW_MODEL_ALIASES = False

if ENABLE_RAW_MODEL_ALIASES:
    for provider, aliases in MODEL_ALIASES.items():
        for alias_key, raw_ids in aliases.items():
            # The main profile for this alias
            main_profile = f"{alias_key}-standard-chat-profile"

            for raw_id in raw_ids:
                # If the raw ID is different from the key, and not already registered
                if raw_id != alias_key and raw_id not in MODEL_GROUP_ALIAS:
                    MODEL_GROUP_ALIAS[raw_id] = [main_profile]

# --- 7. Final Configuration Object ---

CONFIG = {
    "router_settings": {
        "model_group_alias": MODEL_GROUP_ALIAS,
        "agent_metadata": AGENT_ROUTING_METADATA # Export metadata
    },
    "mcp_servers": MCP_SERVERS,
    "model_list": MODEL_LIST,
    "model_aliases": MODEL_ALIASES,
    "agent_settings": AGENT_SETTINGS,
    "cache_settings": CACHE_SETTINGS,
    "key_management_settings": KEY_MANAGEMENT_SETTINGS,
    "auth_settings": AUTH_SETTINGS,
    "native_tool_toggles": NATIVE_TOOL_TOGGLES,
    "enable_smart_search": ENABLE_SMART_SEARCH,
    "enrichment_settings": ENRICHMENT_SETTINGS,
}
