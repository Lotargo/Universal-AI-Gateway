import logging
import asyncio
from collections import deque
from typing import Dict, List, Optional
from core.config.default_config import CONFIG

logger = logging.getLogger(__name__)

class ModelRotationManager:
    """Manages model rotation for different providers and aliases using a Round Robin strategy.

    This class is a Singleton.
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(ModelRotationManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.aliases_config = CONFIG.get("model_aliases", {})
            self._rotation_state: Dict[str, Dict[str, deque]] = {}
            # State for agent load balancing (just a simple counter per alias)
            self._agent_rotation_state: Dict[str, int] = {}
            self._lock = asyncio.Lock()
            self._initialize_state()
            self.initialized = True

    def _initialize_state(self):
        """Initializes the rotation state from the configuration."""
        for provider, aliases in self.aliases_config.items():
            self._rotation_state[provider] = {}
            for alias_name, models in aliases.items():
                # specific models list for this alias
                # We use a deque for efficient rotation
                self._rotation_state[provider][alias_name] = deque(models)
        logger.info("ModelRotationManager initialized.")

    async def get_next_model(self, provider: str, alias_name: str) -> str:
        """Returns the next model for the given provider and alias.

        Rotates the model list (Round Robin).

        Args:
            provider: The name of the provider.
            alias_name: The alias of the model group.

        Returns:
            The next model ID to use.
        """
        async with self._lock:
            provider_state = self._rotation_state.get(provider)
            if not provider_state:
                # If provider not in aliases, maybe it's a raw model ID?
                return alias_name

            model_queue = provider_state.get(alias_name)
            if not model_queue:
                return alias_name

            # Get the first model
            model = model_queue[0]

            # Rotate: move first to last
            model_queue.rotate(-1)

            logger.debug(f"Rotated alias '{alias_name}' (Provider: {provider}). Next model: {model}")
            return model

    async def get_rotation_index(self, alias_name: str, pool_size: int, redis_client=None) -> int:
        """Returns a rotation index for a given alias (e.g. agent name) and pool size.

        Uses Redis for persistence if available, falling back to in-memory.

        Args:
            alias_name: The agent or model group alias.
            pool_size: The number of items to rotate through.
            redis_client: Optional Redis client.

        Returns:
            The index to start at (0 to pool_size - 1).
        """
        if pool_size <= 1:
            return 0

        if redis_client:
            key = f"rotation:index:{alias_name}"
            try:
                # Atomically increment and get value
                # INCR returns the new value
                val = await redis_client.incr(key)
                # Redis INCR is 1-based usually if starting from empty,
                # but we just need a monotonic counter.

                # Calculate modulo
                # We subtract 1 to use 0-based indexing cleanly if desired,
                # though (val % pool_size) is sufficient for rotation.
                current_index = val % pool_size

                logger.debug(f"Agent '{alias_name}' load balance (Redis): index {current_index} (Pool: {pool_size})")
                return current_index
            except Exception as e:
                logger.warning(f"Redis rotation failed for '{alias_name}', falling back to memory: {e}")

        async with self._lock:
            current_index = self._agent_rotation_state.get(alias_name, 0)
            next_index = (current_index + 1) % pool_size
            self._agent_rotation_state[alias_name] = next_index
            logger.debug(f"Agent '{alias_name}' load balance (Memory): index {current_index} -> {next_index} (Pool: {pool_size})")
            return current_index

    def update_aliases(self, new_aliases: Dict):
        """Updates the configuration and resets state if needed."""
        self.aliases_config = new_aliases
        self._initialize_state()

# Global instance
rotation_manager = ModelRotationManager()
