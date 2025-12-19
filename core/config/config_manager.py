# config/config_manager.py
import logging
import copy
from typing import Dict, Any, Optional
from .default_config import CONFIG
from core.common.models import User

logger = logging.getLogger("UniversalAIGateway")

def deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively merges two dictionaries.
    Overrides merge into base.
    """
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class ConfigManager:
    """
    Orchestrates configuration management, handling the hierarchy between
    Global (Default) Config and User-Specific Configs.
    """

    def __init__(self):
        self._global_config = copy.deepcopy(CONFIG)
        logger.info("ConfigManager initialized with default Python configuration.")

    def get_global_config(self) -> Dict[str, Any]:
        """
        Returns the active global configuration.
        """
        return self._global_config

    async def get_config_for_session(
        self,
        session_id: Optional[str] = None,
        user: Optional[User] = None,
        redis_client: Any = None,
        users_repo: Any = None
    ) -> Dict[str, Any]:
        """
        Returns the effective configuration for a given session.
        Merges global config with user-specific overrides if a user is provided.
        If user is NOT provided but session_id is, attempts to look up the user via Redis.
        """
        effective_config = self._global_config

        # 1. Try to resolve User if not provided but session_id + redis + repo are available
        if not user and session_id and redis_client and users_repo:
            try:
                user_id = await redis_client.hget(f"task:{session_id}", "user_id")
                if user_id:
                    user = await users_repo.get_user_by_id(user_id)
            except Exception as e:
                logger.warning(f"Failed to lookup user for session {session_id}: {e}")

        # 2. If we have a user (either passed in or resolved), merge their config overrides
        if user and hasattr(user, "config_overrides") and user.config_overrides:
            logger.debug(f"Applying config overrides for user {user.username}")
            effective_config = deep_merge(effective_config, user.config_overrides)

        return effective_config

    # Alias for compatibility with existing code that expects a single config object
    def get_active_config(self) -> Dict[str, Any]:
        return self.get_global_config()

    def update_global_config(self, new_config: Dict[str, Any]):
        """
        Updates the global configuration at runtime (e.g. from Admin API).
        """
        self._global_config = new_config
        logger.info("Global configuration updated via ConfigManager.")
