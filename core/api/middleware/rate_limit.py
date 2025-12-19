from slowapi import Limiter
from slowapi.util import get_remote_address
import os

def get_limiter():
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = os.getenv("REDIS_PORT", "6379")
    default_redis_url = f"redis://{redis_host}:{redis_port}/0"

    redis_url = os.getenv("REDIS_URL", default_redis_url)
    # If Redis is not available, slowapi falls back to memory storage (if configured)
    # but we explicitly configure it.

    # We use storage_uri to point to Redis.
    # Note: 'limits' library uses 'redis://' scheme.
    return Limiter(
        key_func=get_remote_address,
        storage_uri=redis_url,
        strategy="fixed-window", # or "moving-window"
    )

limiter = get_limiter()

if os.getenv("MOCK_MODE", "false").lower() == "true":
    limiter.enabled = False
