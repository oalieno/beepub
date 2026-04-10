from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth import decode_token


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    token: str | None = Cookie(None),
) -> User:
    """Accept auth from Authorization header or HttpOnly token cookie."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Try Authorization header first (used by SvelteKit SSR internal calls)
    jwt_token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header[7:]
    elif token:
        jwt_token = token

    if not jwt_token:
        raise credentials_exception

    payload = decode_token(jwt_token)
    if payload is None:
        raise credentials_exception
    # Refresh tokens cannot be used to authenticate normal API calls.
    # Tokens issued before the refresh-token feature have no "type" claim,
    # so default to "access" for backward compatibility.
    if payload.get("type", "access") != "access":
        raise credentials_exception
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required"
        )
    return current_user
