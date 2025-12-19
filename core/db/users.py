import uuid
import time
import logging
from typing import Optional, Dict, Any
from core.db.mongo import get_database
from core.common.models import User, UserCreate

logger = logging.getLogger("UniversalAIGateway")

class UsersRepository:
    def __init__(self, db):
        self.collection = db.users

    async def create_user(self, user_create: UserCreate) -> User:
        user_id = str(uuid.uuid4())
        # Generate a secure-looking token
        token = f"sk-magic-{uuid.uuid4().hex}"
        user_doc = {
            "id": user_id,
            "username": user_create.username,
            "token": token,
            "created_at": int(time.time()),
            "provider_keys": {},
            "is_active": True
        }
        await self.collection.insert_one(user_doc)
        logger.info(f"Created new user: {user_create.username} (ID: {user_id})")
        return User(**user_doc)

    async def get_user_by_token(self, token: str) -> Optional[User]:
        user_doc = await self.collection.find_one({"token": token})
        if user_doc:
            return User(**user_doc)
        return None

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        user_doc = await self.collection.find_one({"id": user_id})
        if user_doc:
            return User(**user_doc)
        return None

    async def update_provider_keys(self, user_id: str, keys: Dict[str, str]) -> bool:
        """
        Merges new keys into the existing provider_keys.
        """
        # Construct update dict for specific fields to avoid overwriting existing other keys
        # But simpler: read, update dict, write back? No, race conditions.
        # MongoDB $set with dot notation: {"provider_keys.openai": "..."}

        update_fields = {f"provider_keys.{k}": v for k, v in keys.items()}

        if not update_fields:
            return False

        result = await self.collection.update_one(
            {"id": user_id},
            {"$set": update_fields}
        )
        return result.acknowledged

    async def update_user_config(self, user_id: str, config: Dict[str, Any]) -> bool:
        """
        Updates the user's configuration overrides.
        This replaces the entire 'config_overrides' dictionary for simplicity,
        or we could support partial updates. For now, we replace.
        """
        # To merge: use dot notation if needed, but config can be deep.
        # Replacing the whole object is safer for consistency unless we need deep patch.
        # Let's assume the UI sends the full overrides object.

        result = await self.collection.update_one(
            {"id": user_id},
            {"$set": {"config_overrides": config}}
        )
        return result.acknowledged

async def get_users_repo():
    db = await get_database()
    return UsersRepository(db)
