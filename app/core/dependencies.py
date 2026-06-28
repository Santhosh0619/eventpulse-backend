"""FastAPI dependencies: database session, current user, role enforcement."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import JWTError, decode_token

# ``auto_error=False`` lets us raise our own consistent 401 envelope.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session for the lifetime of a request."""
    async for session in get_session():
        yield session


DBSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DBSession,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)
    ] = None,
):
    """Resolve the authenticated user from a Bearer access token.

    Raises:
        UnauthorizedError: If the token is missing, invalid, of the wrong type,
            or the user no longer exists / is inactive.
    """
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Not authenticated")

    try:
        payload = decode_token(credentials.credentials)
    except JWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc

    if payload.get("type") != "access":
        raise UnauthorizedError("Invalid token type")

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Invalid token payload")

    # Imported lazily: the User model is introduced in Phase 2 (auth/users).
    from app.features.users.models import User

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")

    return user


def require_role(*roles: str):
    """Build a dependency that enforces the current user has one of ``roles``."""

    async def _checker(current_user=Depends(get_current_user)):
        if current_user.role not in roles:
            raise ForbiddenError("Insufficient permissions for this action")
        return current_user

    return _checker
