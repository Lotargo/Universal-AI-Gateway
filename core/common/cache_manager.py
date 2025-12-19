import json
import hashlib
from typing import Optional, Any, Dict
from pydantic import BaseModel
import redis.asyncio as redis

# This module will centralize all caching logic.


async def get_from_cache(key: str, redis_client: redis.Redis) -> Optional[str]:
    """
    Gets a value from the Redis cache.
    """
    if not redis_client:
        return None
    return await redis_client.get(key)


async def set_to_cache(
    key: str, value: str, redis_client: redis.Redis, ttl_seconds: int
):
    """
    Sets a value in the Redis cache with a TTL.
    """
    if not redis_client:
        return
    await redis_client.set(key, value, ex=ttl_seconds)


def create_cache_key(
    request_data: BaseModel, model_config: Dict[str, Any], cache_config: Dict[str, Any]
) -> Optional[str]:
    """
    Creates a cache key based on the request data and caching rules
    defined in the proxy_config.yaml.
    """
    if not cache_config or not cache_config.get("enabled", False):
        return None

    internal_model_name = model_config.get("model_name")
    matching_rule = None

    # Find a rule that applies to the current model
    for rule in cache_config.get("rules", []):
        model_names = rule.get("model_names", [])
        if "*" in model_names or internal_model_name in model_names:
            matching_rule = rule
            break

    # If no rule matches, we don't cache
    if not matching_rule:
        return None

    try:
        # Build a dictionary for hashing based on the fields specified in the rule
        key_dict = {}
        request_dict = request_data.model_dump(exclude_none=True)

        for field in matching_rule.get("include_in_key", []):
            if field in request_dict:
                key_dict[field] = request_dict[field]

        # Always include the internal model name to prevent collisions
        key_dict["internal_model_name"] = internal_model_name

        # If no valid fields were included, don't generate a key
        if not key_dict or len(key_dict) == 1 and "internal_model_name" in key_dict:
            return None

        json_dump = json.dumps(key_dict, sort_keys=True)
        encoded_request = json_dump.encode("utf-8")
        prefix = cache_config.get("key_prefix", "magic_proxy:cache:")

        return f"{prefix}{hashlib.sha256(encoded_request).hexdigest()}"

    except Exception as e:
        # Log the error in a real scenario
        print(f"Error creating cache key: {e}")
        return None
