from fastapi import APIRouter, Depends, Body, HTTPException, status
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
import logging

from core.db.users import get_users_repo, UsersRepository
from core.common.models import User, UserCreate
from core.api.auth_utils import get_current_user_strict

logger = logging.getLogger("UniversalAIGateway")

router = APIRouter()

@router.post("/v1/auth/register", response_model=User, summary="Register a new user")
async def register(
    user_create: UserCreate,
    users_repo: UsersRepository = Depends(get_users_repo)
):
    try:
        user = await users_repo.create_user(user_create)
        return user
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        logger.error(f"Database unavailable during register: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable. Please ensure MongoDB is running."
        )
    except Exception as e:
        logger.error(f"Error registering user: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error during registration."
        )

@router.post("/v1/user/keys", summary="Update provider API keys for the current user")
async def update_keys(
    keys: dict = Body(..., description="Dictionary of provider keys (e.g. {'openai': 'sk-...'})"),
    user: User = Depends(get_current_user_strict),
    users_repo: UsersRepository = Depends(get_users_repo)
):
    try:
        success = await users_repo.update_provider_keys(user.id, keys)
        return {"status": "success", "updated": success, "user_id": user.id}
    except (ServerSelectionTimeoutError, ConnectionFailure) as e:
        logger.error(f"Database unavailable during key update: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable. Please ensure MongoDB is running."
        )
    except Exception as e:
        logger.error(f"Error updating keys: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal Server Error during key update."
        )

@router.get("/v1/user/me", response_model=User, summary="Get current user info")
async def get_me(user: User = Depends(get_current_user_strict)):
    return user
