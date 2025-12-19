import time
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pymongo.errors import ServerSelectionTimeoutError, ConnectionFailure
from core.db.users import get_users_repo, UsersRepository
from core.common.models import User

# auto_error=False allows us to handle the missing header manually (e.g. for fallback or custom error)
security = HTTPBearer(auto_error=False)

async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
    users_repo: UsersRepository = Depends(get_users_repo)
) -> Optional[User]:
    """
    Dependency to retrieve the current authenticated user.
    Handles 'AUTH_ENABLED=False' fallback.
    """
    config = getattr(request.app.state, "config", {})
    auth_enabled = config.get("auth_settings", {}).get("enabled", True)

    if not auth_enabled:
        # --- Auth Disabled Mode ---
        token_val = creds.credentials if creds else "disabled-auth-token"

        # 1. Best Effort: Try to resolve real user if token is present
        # This allows users with valid keys to still use their provider_keys.
        if creds:
            try:
                user = await users_repo.get_user_by_token(token_val)
                if user:
                    return user
            except Exception:
                # In disabled mode, DB errors shouldn't block the request
                pass

        # 2. Fallback: Return Anonymous User
        # We accept ANY token value as requested.
        return User(
            id="anonymous",
            username="anonymous",
            token=token_val,
            created_at=int(time.time()),
            provider_keys={}
        )

    # --- Strict Auth Mode ---
    if not creds:
        return None

    token = creds.credentials

    try:
        user = await users_repo.get_user_by_token(token)
    except (ServerSelectionTimeoutError, ConnectionFailure):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable during authentication. Please ensure MongoDB is running."
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

async def get_current_user_strict(
    user: Optional[User] = Depends(get_current_user)
) -> User:
    """
    Enforces authentication. Raises 401 if user is None.
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
